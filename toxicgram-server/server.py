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
        """)

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
                if cmd and cmd[0].split("@")[0] in ("/start","/code"):
                    result=issue(sender["id"])
                    if result:
                        n,code=result
                        reply=f"Toxicgram\nВаш виртуальный номер: {n}\nКод Toxicgram: {code}\nДействует 5 минут. Не пересылайте код. Для нового кода: /code"
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
    n=body.number.strip().upper()
    code=body.code.strip().replace(" ","")
    if not re.fullmatch(r"TG-[0-9]{4}-[0-9]{4}",n) or not re.fullmatch(r"[0-9]{6}",code):
        raise HTTPException(401,"Invalid or expired credentials")
    token=consume(n,code)
    if not token:
        raise HTTPException(401,"Invalid or expired credentials")
    return {"access_token":token,"token_type":"bearer","expires_in":TTL,"number":n}

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
    return {"number":session(request)[1]}

@app.post("/v1/auth/logout")
def logout(request:Request):
    key,_=session(request)
    with db() as c:
        c.execute("DELETE FROM sessions WHERE token_hash=?",(key,))
    return {"ok":True}

class ProfileUpdate(BaseModel):
    name: str = Field(min_length=1,max_length=64)

class MessageCreate(BaseModel):
    recipient: str = Field(max_length=32)
    text: str = Field(min_length=1,max_length=4000)

def normalize_number(value):
    value=value.strip().upper()
    if not re.fullmatch(r"TG-[0-9]{4}-[0-9]{4}",value):
        raise HTTPException(400,"Invalid Toxicgram number")
    return value

def require_peer(c, number):
    if not c.execute("SELECT 1 FROM accounts WHERE number=?",(number,)).fetchone():
        raise HTTPException(404,"Account not found")

@app.get("/v1/profile")
def profile(request:Request):
    _,n=session(request)
    with db() as c:
        row=c.execute("SELECT name FROM profiles WHERE number=?",(n,)).fetchone()
    return {"number":n,"name":row["name"] if row else n}

@app.put("/v1/profile")
def update_profile(body:ProfileUpdate,request:Request):
    _,n=session(request)
    name=body.name.strip()
    if not name:
        raise HTTPException(400,"Empty name")
    with db() as c:
        c.execute("INSERT INTO profiles VALUES (?,?) ON CONFLICT(number) DO UPDATE SET name=excluded.name",(n,name))
    return {"number":n,"name":name}

@app.get("/v1/users/{number}")
def lookup(number:str,request:Request):
    _,n=session(request)
    if not allow("lookup:"+n):
        raise HTTPException(429,"Too many requests")
    peer=normalize_number(number)
    with db() as c:
        require_peer(c,peer)
        row=c.execute("SELECT name FROM profiles WHERE number=?",(peer,)).fetchone()
    return {"number":peer,"name":row["name"] if row else peer}

@app.get("/v1/chats")
def chats(request:Request):
    _,n=session(request)
    with db() as c:
        rows=c.execute("""
        WITH relevant AS (
          SELECT *, CASE WHEN sender=? THEN recipient ELSE sender END AS peer
          FROM messages WHERE sender=? OR recipient=?
        ), latest AS (SELECT peer,MAX(id) AS id FROM relevant GROUP BY peer)
        SELECT r.peer AS number,COALESCE(p.name,r.peer) AS name,r.body AS text,r.created,r.id
        FROM latest l JOIN relevant r ON r.id=l.id LEFT JOIN profiles p ON p.number=r.peer
        ORDER BY r.id DESC LIMIT 100
        """,(n,n,n)).fetchall()
    return {"chats":[dict(row) for row in rows]}

@app.get("/v1/chats/{number}/messages")
def history(number:str,request:Request,after:int=0,before:int=0):
    _,n=session(request)
    peer=normalize_number(number)
    if after<0 or before<0 or (after and before):
        raise HTTPException(400,"Invalid cursor")
    with db() as c:
        require_peer(c,peer)
        base="SELECT id,sender,recipient,body AS text,created FROM messages WHERE ((sender=? AND recipient=?) OR (sender=? AND recipient=?))"
        args=(n,peer,peer,n)
        if after:
            rows=c.execute(base+" AND id>? ORDER BY id ASC LIMIT 100",args+(after,)).fetchall()
        elif before:
            rows=list(reversed(c.execute(base+" AND id<? ORDER BY id DESC LIMIT 100",args+(before,)).fetchall()))
        else:
            rows=list(reversed(c.execute(base+" ORDER BY id DESC LIMIT 100",args).fetchall()))
    return {"messages":[dict(row) for row in rows]}

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
        cur=c.execute("INSERT INTO messages(sender,recipient,body,created) VALUES (?,?,?,?)",(n,peer,value,now))
        mid=cur.lastrowid
    return {"id":mid,"sender":n,"recipient":peer,"text":value,"created":now}
