import hashlib, hmac, json, os, re, secrets, sqlite3, threading, time, urllib.request
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

DB = os.getenv("TOXICGRAM_DB", "data/toxicgram.sqlite3")
TOKEN = os.getenv("BOT_TOKEN", "")
PEPPER = os.getenv("AUTH_SECRET", "")
TTL = 30*86400

@contextmanager
def db():
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=15, isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()

def init():
    with db() as c:
        c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS accounts (telegram_id INTEGER PRIMARY KEY, number TEXT UNIQUE NOT NULL, code_hash TEXT, expires INTEGER DEFAULT 0, issued INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, number TEXT NOT NULL, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS limits (key TEXT PRIMARY KEY, window INTEGER, count INTEGER);
        CREATE TABLE IF NOT EXISTS profiles (number TEXT PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL, recipient TEXT NOT NULL, body TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS msg_sender_recipient ON messages(sender,recipient,id);
        CREATE INDEX IF NOT EXISTS msg_recipient_sender ON messages(recipient,sender,id);
        CREATE TABLE IF NOT EXISTS chat_settings (owner TEXT NOT NULL, peer TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(owner,peer));
        CREATE TABLE IF NOT EXISTS hidden_messages (owner TEXT NOT NULL, message_id INTEGER NOT NULL, PRIMARY KEY(owner,message_id));
        CREATE TABLE IF NOT EXISTS read_state (owner TEXT NOT NULL, peer TEXT NOT NULL, last_id INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(owner,peer));
        CREATE TABLE IF NOT EXISTS message_edits (message_id INTEGER PRIMARY KEY, edited INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS phone_aliases (number TEXT PRIMARY KEY, phone TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS profile_details (number TEXT PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE, bio TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS reactions (message_id INTEGER NOT NULL, owner TEXT NOT NULL, emoji TEXT NOT NULL, PRIMARY KEY(message_id,owner));
        CREATE TABLE IF NOT EXISTS blocks (owner TEXT NOT NULL, peer TEXT NOT NULL, PRIMARY KEY(owner,peer));
        CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL, kind TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS room_members (room_id TEXT NOT NULL, number TEXT NOT NULL, PRIMARY KEY(room_id,number));
        CREATE TABLE IF NOT EXISTS room_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL, sender TEXT NOT NULL, body TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS room_history ON room_messages(room_id,id);
        """)

def phone_for(n, prefix=None):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT phone FROM phone_aliases WHERE number=?",(n,)).fetchone()
        if row and (prefix is None or row["phone"].startswith(prefix+"000")):
            c.commit()
            return row["phone"]
        prefix=prefix or "+388"
        if prefix not in ("+7","+1","+388"):
            raise ValueError("Unsupported virtual prefix")
        while True:
            phone=prefix+"000"+f"{secrets.randbelow(10000000):07d}"
            if not c.execute("SELECT 1 FROM phone_aliases WHERE phone=?",(phone,)).fetchone():
                break
        c.execute("INSERT INTO phone_aliases VALUES (?,?) ON CONFLICT(number) DO UPDATE SET phone=excluded.phone",(n,phone))
        c.commit()
        return phone

def public_profile(n):
    phone=phone_for(n)
    with db() as c:
        row=c.execute("SELECT name FROM profiles WHERE number=?",(n,)).fetchone()
        details=c.execute("SELECT username,bio FROM profile_details WHERE number=?",(n,)).fetchone()
    return {"number":n,"phone":phone,"name":row["name"] if row else phone,"username":(details["username"] or "") if details else "","bio":details["bio"] if details else ""}

def digest(s):
    return hmac.new(PEPPER.encode(), s.encode(), hashlib.sha256).hexdigest()

def issue(tid):
    now = int(time.time())
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM accounts WHERE telegram_id=?", (tid,)).fetchone()
        if row and now-row["issued"]<30:
            c.rollback()
            return None
        if row:
            n = row["number"]
        else:
            while True:
                d = f"{secrets.randbelow(100000000):08d}"
                n = f"TG-{d[:4]}-{d[4:]}"
                if not c.execute("SELECT 1 FROM accounts WHERE number=?", (n,)).fetchone():
                    break
            c.execute("INSERT INTO accounts(telegram_id,number) VALUES (?,?)", (tid,n))
        code = f"{secrets.randbelow(1000000):06d}"
        c.execute("UPDATE accounts SET code_hash=?,expires=?,issued=?,attempts=0 WHERE telegram_id=?", (digest(n+":"+code),now+300,now,tid))
        c.commit()
        return n,code

def consume(n,code):
    now = int(time.time())
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM accounts WHERE number=?", (n,)).fetchone()
        if not row or not row["code_hash"] or row["expires"]<=now or row["attempts"]>=5:
            c.rollback()
            return None
        if not hmac.compare_digest(row["code_hash"],digest(n+":"+code)):
            c.execute("UPDATE accounts SET attempts=attempts+1 WHERE number=?", (n,))
            c.commit()
            return None
        token = secrets.token_urlsafe(32)
        c.execute("UPDATE accounts SET code_hash=NULL,expires=0 WHERE number=?", (n,))
        c.execute("DELETE FROM sessions WHERE expires<=?", (now,))
        c.execute("INSERT INTO sessions VALUES (?,?,?)", (digest(token),n,now+TTL))
        c.commit()
        return token

def allow(key):
    w = int(time.time())//60
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("DELETE FROM limits WHERE window<?", (w-1,))
        c.execute("INSERT INTO limits VALUES (?,?,1) ON CONFLICT(key) DO UPDATE SET count=CASE WHEN window=excluded.window THEN count+1 ELSE 1 END,window=excluded.window", (key,w))
        count = c.execute("SELECT count FROM limits WHERE key=?", (key,)).fetchone()[0]
        c.commit()
        return count<=30

def api(method,payload):
    req=urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=40) as response:
        return json.load(response)["result"]

def poll(stop):
    offset=0
    while not stop.is_set():
        try:
            for u in api("getUpdates",{"offset":offset,"timeout":25,"allowed_updates":["message"]}):
                offset=u["update_id"]+1
                m=u.get("message",{})
                chat=m.get("chat",{})
                sender=m.get("from",{})
                if chat.get("type")!="private" or not sender.get("id"):
                    continue
                cmd=m.get("text","").strip().split(maxsplit=1)
                if cmd and cmd[0].split("@")[0] in ("/start","/code","/number"):
                    prefix=None
                    if cmd[0].split("@")[0]=="/number":
                        if len(cmd)!=2 or cmd[1] not in ("+7","+1","+388"):
                            api("sendMessage",{"chat_id":chat["id"],"text":"Выберите виртуальный префикс: /number +7, /number +1 или /number +388. Это внутренние номера, не SIM-карты."})
                            continue
                        prefix=cmd[1]
                    result=issue(sender["id"])
                    if result:
                        n,code=result
                        phone=phone_for(n,prefix)
                        reply=f"Toxicgram\nВаш виртуальный номер: {phone}\nКод Toxicgram: {code}\nДействует 5 минут. Не пересылайте код.\nТолько для Toxicgram, не настоящий телефон.\nПрефикс: /number +7, /number +1, /number +388.\nСтарый ID: {n}"
                    else:
                        reply="Подождите 30 секунд перед запросом нового кода."
                else:
                    reply="Используйте /code для получения кода Toxicgram."
                api("sendMessage",{"chat_id":chat["id"],"text":reply,"protect_content":True})
        except Exception:
            print("Bot polling failed; retrying.",flush=True)
            stop.wait(5)

@asynccontextmanager
async def lifespan(app):
    if len(PEPPER)<32:
        raise RuntimeError("AUTH_SECRET must have at least 32 characters")
    init()
    stop=threading.Event()
    if TOKEN:
        threading.Thread(target=poll,args=(stop,),daemon=True).start()
    yield
    stop.set()

app=FastAPI(title="Toxicgram Auth",lifespan=lifespan)
class Login(BaseModel):
    number:str=Field(max_length=32)
    code:str=Field(max_length=16)

@app.get("/health")
def health():
    return {"status":"ok","bot_configured":bool(TOKEN)}

@app.post("/v1/auth/verify")
def verify(body:Login,request:Request):
    if not allow("ip:"+(request.client.host if request.client else "unknown")):
        raise HTTPException(429,"Too many requests")
    try:
        n=normalize_number(body.number)
    except HTTPException:
        raise HTTPException(401,"Invalid or expired credentials")
    code=body.code.strip().replace(" ","")
    if not re.fullmatch(r"[0-9]{6}",code):
        raise HTTPException(401,"Invalid or expired credentials")
    token=consume(n,code)
    if not token:
        raise HTTPException(401,"Invalid or expired credentials")
    return {"access_token":token,"token_type":"bearer","expires_in":TTL,"number":n,"phone":phone_for(n)}

def session(request):
    scheme,_,token=request.headers.get("Authorization","").partition(" ")
    if scheme.lower()!="bearer" or not token or len(token)>128:
        raise HTTPException(401,"Unauthorized")
    key=digest(token)
    with db() as c:
        row=c.execute("SELECT number FROM sessions WHERE token_hash=? AND expires>?",(key,int(time.time()))).fetchone()
    if not row:
        raise HTTPException(401,"Unauthorized")
    return key,row["number"]

@app.get("/v1/me")
def me(request:Request):
    return public_profile(session(request)[1])

@app.post("/v1/auth/logout")
def logout(request:Request):
    key,_=session(request)
    with db() as c:
        c.execute("DELETE FROM sessions WHERE token_hash=?",(key,))
    return {"ok":True}

class ProfileUpdate(BaseModel):
    name: str = Field(min_length=1,max_length=64)
    username: str | None = Field(default=None,max_length=32)
    bio: str | None = Field(default=None,max_length=160)

class MessageCreate(BaseModel):
    recipient: str = Field(max_length=32)
    text: str = Field(min_length=1,max_length=4000)

def normalize_number(value):
    value=value.strip()
    if re.fullmatch(r"TG-[0-9]{4}-[0-9]{4}",value.upper()):
        return value.upper()
    with db() as c:
        if value.startswith("@") and re.fullmatch(r"@[A-Za-z0-9_]{5,32}",value):
            row=c.execute("SELECT number FROM profile_details WHERE username=? COLLATE NOCASE",(value[1:],)).fetchone()
        else:
            compact=re.sub(r"[\s()-]","",value)
            if not re.fullmatch(r"\+(?:7|1|388)000[0-9]{7}",compact):
                raise HTTPException(400,"Invalid Toxicgram number")
            row=c.execute("SELECT number FROM phone_aliases WHERE phone=?",(compact,)).fetchone()
    if not row: raise HTTPException(404,"Account not found")
    return row["number"]

def require_peer(c, number):
    if not c.execute("SELECT 1 FROM accounts WHERE number=?",(number,)).fetchone():
        raise HTTPException(404,"Account not found")

@app.get("/v1/profile")
def profile(request:Request):
    _,n=session(request)
    return public_profile(n)

@app.put("/v1/profile")
def update_profile(body:ProfileUpdate,request:Request):
    _,n=session(request)
    name=body.name.strip()
    if not name:
        raise HTTPException(400,"Empty name")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO profiles VALUES (?,?) ON CONFLICT(number) DO UPDATE SET name=excluded.name",(n,name))
        c.execute("INSERT OR IGNORE INTO profile_details(number) VALUES (?)",(n,))
        if body.username is not None:
            username=body.username.strip().lstrip("@").lower()
            if username and not re.fullmatch(r"[a-z0-9_]{5,32}",username):
                raise HTTPException(400,"Invalid username")
            try:
                c.execute("UPDATE profile_details SET username=? WHERE number=?",(username or None,n))
            except sqlite3.IntegrityError:
                raise HTTPException(409,"Username taken")
        if body.bio is not None:
            c.execute("UPDATE profile_details SET bio=? WHERE number=?",(body.bio.strip(),n))
        c.commit()
    return public_profile(n)

@app.get("/v1/users/{number}")
def lookup(number:str,request:Request):
    _,n=session(request)
    if not allow("lookup:"+n):
        raise HTTPException(429,"Too many requests")
    peer=normalize_number(number)
    with db() as c:
        require_peer(c,peer)
        pass
    return public_profile(peer)

@app.get("/v1/chats")
def chats(request:Request):
    _,n=session(request)
    with db() as c:
        rows=c.execute("""
        WITH relevant AS (
          SELECT *, CASE WHEN sender=? THEN recipient ELSE sender END AS peer
          FROM messages WHERE (sender=? OR recipient=?) AND NOT EXISTS (SELECT 1 FROM hidden_messages h WHERE h.owner=? AND h.message_id=messages.id)
        ), latest AS (SELECT peer,MAX(id) AS id FROM relevant GROUP BY peer)
        SELECT r.peer AS number,COALESCE(p.name,r.peer) AS name,r.body AS text,r.created,r.id, COALESCE(s.pinned,0) AS pinned, COALESCE(s.archived,0) AS archived, (SELECT COUNT(*) FROM relevant v WHERE v.peer=r.peer AND v.sender=r.peer AND v.sender<>? AND v.id>COALESCE(rs.last_id,0)) AS unread
        FROM latest l JOIN relevant r ON r.id=l.id LEFT JOIN profiles p ON p.number=r.peer
        LEFT JOIN chat_settings s ON s.owner=? AND s.peer=r.peer LEFT JOIN read_state rs ON rs.owner=? AND rs.peer=r.peer
        ORDER BY pinned DESC,r.id DESC LIMIT 100
        """,(n,n,n,n,n,n,n)).fetchall()
    result=[]
    for row in rows:
        item=dict(row)
        item["phone"]=phone_for(item["number"])
        if item["name"]==item["number"]: item["name"]=item["phone"]
        result.append(item)
    return {"chats":result}

@app.get("/v1/chats/{number}/messages")
def history(number:str,request:Request,after:int=0,before:int=0):
    _,n=session(request)
    peer=normalize_number(number)
    if after<0 or before<0 or (after and before):
        raise HTTPException(400,"Invalid cursor")
    with db() as c:
        require_peer(c,peer)
        base="SELECT id,sender,recipient,body AS text,created,COALESCE((SELECT edited FROM message_edits e WHERE e.message_id=messages.id),0) AS edited FROM messages WHERE ((sender=? AND recipient=?) OR (sender=? AND recipient=?)) AND NOT EXISTS (SELECT 1 FROM hidden_messages h WHERE h.owner=? AND h.message_id=messages.id)"
        args=(n,peer,peer,n,n)
        if after:
            rows=c.execute(base+" AND id>? ORDER BY id ASC LIMIT 100",args+(after,)).fetchall()
        elif before:
            rows=list(reversed(c.execute(base+" AND id<? ORDER BY id DESC LIMIT 100",args+(before,)).fetchall()))
        else:
            rows=list(reversed(c.execute(base+" ORDER BY id DESC LIMIT 100",args).fetchall()))
        result=[]
        for row in rows:
            item=dict(row)
            item["reactions"]=[dict(x) for x in c.execute("SELECT emoji,COUNT(*) AS count FROM reactions WHERE message_id=? GROUP BY emoji",(item["id"],))]
            item["read"]=bool(c.execute("SELECT 1 FROM read_state WHERE owner=? AND peer=? AND last_id>=?",(item["recipient"],item["sender"],item["id"])).fetchone()) or item["recipient"]==item["sender"]
            result.append(item)
    return {"messages":result}

@app.post("/v1/messages")
def send(body:MessageCreate,request:Request):
    _,n=session(request)
    if not allow("send:"+n):
        raise HTTPException(429,"Too many messages")
    peer=normalize_number(body.recipient)
    value=body.text.strip()
    if not value:
        raise HTTPException(400,"Empty message")
    now=int(time.time())
    with db() as c:
        require_peer(c,peer)
        if c.execute("SELECT 1 FROM blocks WHERE (owner=? AND peer=?) OR (owner=? AND peer=?)",(n,peer,peer,n)).fetchone():
            raise HTTPException(403,"Messaging unavailable")
        cur=c.execute("INSERT INTO messages(sender,recipient,body,created) VALUES (?,?,?,?)",(n,peer,value,now))
        mid=cur.lastrowid
    return {"id":mid,"sender":n,"recipient":peer,"text":value,"created":now}

class EditMessage(BaseModel):
    text: str = Field(min_length=1,max_length=4000)

class ChatSettings(BaseModel):
    pinned: bool | None = None
    archived: bool | None = None

class MarkRead(BaseModel):
    last_id: int = Field(ge=0)

def own_message(c, n, mid):
    row=c.execute("SELECT * FROM messages WHERE id=? AND (sender=? OR recipient=?)",(mid,n,n)).fetchone()
    if not row:
        raise HTTPException(404,"Message not found")
    return row

@app.put("/v1/messages/{mid}")
def edit_message(mid:int, body:EditMessage, request:Request):
    _,n=session(request)
    value=body.text.strip()
    if not value: raise HTTPException(400,"Empty message")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        row=own_message(c,n,mid)
        if row["sender"]!=n: raise HTTPException(403,"Only sender can edit")
        c.execute("UPDATE messages SET body=? WHERE id=?",(value,mid))
        c.execute("INSERT INTO message_edits VALUES (?,?) ON CONFLICT(message_id) DO UPDATE SET edited=excluded.edited",(mid,int(time.time())))
        c.commit()
    return {"ok":True}

@app.delete("/v1/messages/{mid}")
def delete_message(mid:int,request:Request,everyone:bool=False):
    _,n=session(request)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        row=own_message(c,n,mid)
        if everyone:
            if row["sender"]!=n: raise HTTPException(403,"Only sender can delete for everyone")
            c.execute("DELETE FROM messages WHERE id=?",(mid,))
            c.execute("DELETE FROM hidden_messages WHERE message_id=?",(mid,))
            c.execute("DELETE FROM message_edits WHERE message_id=?",(mid,))
            c.execute("DELETE FROM reactions WHERE message_id=?",(mid,))
        else:
            c.execute("INSERT OR IGNORE INTO hidden_messages VALUES (?,?)",(n,mid))
        c.commit()
    return {"ok":True}

@app.put("/v1/chats/{number}/settings")
def chat_settings(number:str, body:ChatSettings,request:Request):
    _,n=session(request)
    peer=normalize_number(number)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        require_peer(c,peer)
        c.execute("INSERT OR IGNORE INTO chat_settings(owner,peer) VALUES (?,?)",(n,peer))
        if body.pinned is not None: c.execute("UPDATE chat_settings SET pinned=? WHERE owner=? AND peer=?",(int(body.pinned),n,peer))
        if body.archived is not None: c.execute("UPDATE chat_settings SET archived=? WHERE owner=? AND peer=?",(int(body.archived),n,peer))
        c.commit()
    return {"ok":True}

@app.put("/v1/chats/{number}/read")
def mark_read(number:str,body:MarkRead,request:Request):
    _,n=session(request)
    peer=normalize_number(number)
    with db() as c:
        require_peer(c,peer)
        last=c.execute("SELECT COALESCE(MAX(id),0) FROM messages WHERE sender=? AND recipient=? AND id<=?",(peer,n,body.last_id)).fetchone()[0]
        c.execute("INSERT INTO read_state VALUES (?,?,?) ON CONFLICT(owner,peer) DO UPDATE SET last_id=MAX(last_id,excluded.last_id)",(n,peer,last))
    return {"ok":True}

class Reaction(BaseModel):
    emoji: str = Field(max_length=16)

@app.put("/v1/messages/{mid}/reaction")
def react(mid:int, body:Reaction, request:Request):
    _,n=session(request)
    if body.emoji not in ("","👍","❤️","🔥","😂","😢","👎"):
        raise HTTPException(400,"Unsupported reaction")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        own_message(c,n,mid)
        if body.emoji:
            c.execute("INSERT INTO reactions VALUES (?,?,?) ON CONFLICT(message_id,owner) DO UPDATE SET emoji=excluded.emoji",(mid,n,body.emoji))
        else:
            c.execute("DELETE FROM reactions WHERE message_id=? AND owner=?",(mid,n))
        c.commit()
    return {"ok":True}

class BlockUpdate(BaseModel):
    blocked: bool

@app.put("/v1/users/{number}/block")
def block(number:str,body:BlockUpdate,request:Request):
    _,n=session(request)
    peer=normalize_number(number)
    if peer==n: raise HTTPException(400,"Cannot block yourself")
    with db() as c:
        require_peer(c,peer)
        if body.blocked: c.execute("INSERT OR IGNORE INTO blocks VALUES (?,?)",(n,peer))
        else: c.execute("DELETE FROM blocks WHERE owner=? AND peer=?",(n,peer))
    return {"ok":True}

class RoomCreate(BaseModel):
    title: str = Field(min_length=1,max_length=80)
    kind: str = Field(max_length=10)

class RoomInvite(BaseModel):
    number: str = Field(max_length=40)

class RoomText(BaseModel):
    text: str = Field(min_length=1,max_length=4000)

def get_room(c, rid, n):
    row=c.execute("SELECT r.* FROM rooms r JOIN room_members m ON m.room_id=r.id WHERE r.id=? AND m.number=?",(rid,n)).fetchone()
    if not row: raise HTTPException(404,"Room not found")
    return row

@app.post("/v1/rooms")
def create_room(body:RoomCreate,request:Request):
    _,n=session(request)
    if not allow("room_create:"+n): raise HTTPException(429,"Too many requests")
    title=body.title.strip()
    if not title or body.kind not in ("group","channel"): raise HTTPException(400,"Invalid room")
    rid=secrets.token_hex(12)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO rooms VALUES (?,?,?,?)",(rid,n,title,body.kind))
        c.execute("INSERT INTO room_members VALUES (?,?)",(rid,n))
        c.commit()
    return {"id":rid,"title":title,"kind":body.kind,"owner":n}

@app.get("/v1/rooms")
def list_rooms(request:Request):
    _,n=session(request)
    with db() as c:
        rows=c.execute("SELECT r.*, (SELECT COUNT(*) FROM room_members x WHERE x.room_id=r.id) AS members FROM rooms r JOIN room_members m ON r.id=m.room_id WHERE m.number=? ORDER BY r.title COLLATE NOCASE LIMIT 100",(n,)).fetchall()
    return {"rooms":[dict(row) for row in rows]}

@app.post("/v1/rooms/{rid}/invite")
def invite_room(rid:str,body:RoomInvite,request:Request):
    _,n=session(request)
    if not allow("invite:"+n): raise HTTPException(429,"Too many requests")
    peer=normalize_number(body.number)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        row=get_room(c,rid,n)
        if row["owner"]!=n: raise HTTPException(403,"Only owner can invite")
        require_peer(c,peer)
        if c.execute("SELECT 1 FROM blocks WHERE (owner=? AND peer=?) OR (owner=? AND peer=?)",(n,peer,peer,n)).fetchone(): raise HTTPException(403,"Invitation unavailable")
        c.execute("INSERT OR IGNORE INTO room_members VALUES (?,?)",(rid,peer))
        c.commit()
    return {"ok":True}

@app.get("/v1/rooms/{rid}/messages")
def room_history(rid:str,request:Request):
    _,n=session(request)
    with db() as c:
        get_room(c,rid,n)
        rows=c.execute("SELECT m.id,m.sender,m.body AS text,m.created,COALESCE(p.name,m.sender) AS name FROM room_messages m LEFT JOIN profiles p ON p.number=m.sender WHERE m.room_id=? ORDER BY m.id DESC LIMIT 100",(rid,)).fetchall()
    return {"messages":[dict(row) for row in reversed(rows)]}

@app.post("/v1/rooms/{rid}/messages")
def room_send(rid:str,body:RoomText,request:Request):
    _,n=session(request)
    if not allow("send:"+n): raise HTTPException(429,"Too many messages")
    value=body.text.strip()
    if not value: raise HTTPException(400,"Empty message")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        row=get_room(c,rid,n)
        if row["kind"]=="channel" and row["owner"]!=n: raise HTTPException(403,"Only owner can post")
        mid=c.execute("INSERT INTO room_messages(room_id,sender,body,created) VALUES (?,?,?,?)",(rid,n,value,int(time.time()))).lastrowid
        c.commit()
    return {"id":mid}

@app.delete("/v1/rooms/{rid}/membership")
def leave_room(rid:str,request:Request):
    _,n=session(request)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        row=get_room(c,rid,n)
        if row["owner"]==n: raise HTTPException(400,"Owner cannot leave")
        c.execute("DELETE FROM room_members WHERE room_id=? AND number=?",(rid,n))
        c.commit()
    return {"ok":True}
