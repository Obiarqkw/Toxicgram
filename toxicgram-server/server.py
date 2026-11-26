import hashlib, hmac, json, os, re, secrets, sqlite3, threading, time, urllib.request
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.concurrency import run_in_threadpool
import base64, binascii, gzip, io
from fastapi.responses import HTMLResponse
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
        CREATE TABLE IF NOT EXISTS referral_codes (number TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS referrals (invitee TEXT PRIMARY KEY, inviter TEXT NOT NULL, created INTEGER NOT NULL, rewarded_at INTEGER NOT NULL DEFAULT 0, reward INTEGER NOT NULL DEFAULT 0, CHECK(invitee<>inviter));
        CREATE INDEX IF NOT EXISTS referrals_inviter ON referrals(inviter,rewarded_at);
        CREATE TABLE IF NOT EXISTS registrations (number TEXT PRIMARY KEY, registered_at INTEGER NOT NULL);
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
        CREATE TABLE IF NOT EXISTS used_phones (phone TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS presence (number TEXT PRIMARY KEY, last_seen INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS msg_incoming_cursor ON messages(recipient,id);
        CREATE TABLE IF NOT EXISTS profile_names (number TEXT PRIMARY KEY, first_name TEXT NOT NULL, last_name TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS room_meta (numeric_id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT UNIQUE NOT NULL, about TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'basic', created INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS profile_details (number TEXT PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE, bio TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS reactions (message_id INTEGER NOT NULL, owner TEXT NOT NULL, emoji TEXT NOT NULL, PRIMARY KEY(message_id,owner));
        CREATE TABLE IF NOT EXISTS blocks (owner TEXT NOT NULL, peer TEXT NOT NULL, PRIMARY KEY(owner,peer));
        CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL, kind TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS room_members (room_id TEXT NOT NULL, number TEXT NOT NULL, PRIMARY KEY(room_id,number));
        CREATE TABLE IF NOT EXISTS room_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL, sender TEXT NOT NULL, body TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS room_history ON room_messages(room_id,id);
        CREATE TABLE IF NOT EXISTS media (id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, mime TEXT NOT NULL, content BLOB NOT NULL, size INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS message_media (message_id INTEGER PRIMARY KEY, media_id TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS avatars (number TEXT PRIMARY KEY, media_id TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS wallets (number TEXT PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 1000);
        CREATE TABLE IF NOT EXISTS gifts (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL, recipient TEXT NOT NULL, kind TEXT NOT NULL, created INTEGER NOT NULL, serial TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS gift_details (gift_id INTEGER PRIMARY KEY, visible INTEGER NOT NULL DEFAULT 0, anonymous INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS gift_orders (sender TEXT NOT NULL, request_id TEXT NOT NULL, gift_id INTEGER NOT NULL, PRIMARY KEY(sender,request_id));
        CREATE TABLE IF NOT EXISTS catalog_gifts (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT UNIQUE NOT NULL, name TEXT NOT NULL, emoji TEXT NOT NULL DEFAULT '', price INTEGER NOT NULL, supply INTEGER NOT NULL DEFAULT 0, issued INTEGER NOT NULL DEFAULT 0, rarity TEXT NOT NULL DEFAULT 'common', upgrade_enabled INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, art TEXT NOT NULL DEFAULT '', asset TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS gift_art (id TEXT PRIMARY KEY, data BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS gift_numbers (gift_id INTEGER PRIMARY KEY, num INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS account_freezes (number TEXT PRIMARY KEY, reason TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS admin_user_actions (id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, reason TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS admin_user_action_number ON admin_user_actions(number,id);
        CREATE TABLE IF NOT EXISTS admin_user_requests (request_id TEXT PRIMARY KEY, signature TEXT NOT NULL, result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS admin_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, kind TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS stories (id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, text TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS story_owner ON stories(owner,created);
        """)
        c.execute("INSERT OR IGNORE INTO room_meta(room_id,mode) SELECT id,CASE WHEN kind='channel' THEN 'channel' ELSE 'basic' END FROM rooms ORDER BY rowid")
        seed_catalog(c)

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
            if not c.execute("SELECT 1 FROM used_phones WHERE phone=? UNION SELECT 1 FROM phone_aliases WHERE phone=?",(phone,phone)).fetchone():
                break
        if row: c.execute("INSERT OR IGNORE INTO used_phones VALUES (?)",(row["phone"],))
        c.execute("INSERT OR IGNORE INTO used_phones VALUES (?)",(phone,))
        c.execute("INSERT INTO phone_aliases VALUES (?,?) ON CONFLICT(number) DO UPDATE SET phone=excluded.phone",(n,phone))
        c.commit()
        return phone

def public_profile(n):
    phone=phone_for(n)
    with db() as c:
        row=c.execute("SELECT name FROM profiles WHERE number=?",(n,)).fetchone()
        details=c.execute("SELECT username,bio FROM profile_details WHERE number=?",(n,)).fetchone()
        avatar=c.execute("SELECT media_id FROM avatars WHERE number=?",(n,)).fetchone()
        names=c.execute("SELECT first_name,last_name FROM profile_names WHERE number=?",(n,)).fetchone()
        gift_count=c.execute("SELECT COUNT(*) FROM gifts g LEFT JOIN gift_details d ON g.id=d.gift_id WHERE g.recipient=? AND d.visible=1",(n,)).fetchone()[0]
    return {"first_name":names["first_name"] if names else (row["name"] if row else phone),"last_name":names["last_name"] if names else "","gift_count":gift_count,"avatar":avatar["media_id"] if avatar else "","number":n,"phone":phone,"name":row["name"] if row else phone,"username":(details["username"] or "") if details else "","bio":details["bio"] if details else ""}

def digest(s):
    return hmac.new(PEPPER.encode(), s.encode(), hashlib.sha256).hexdigest()

REFERRAL_REWARD=500

def referral_stats(tid):
    """Only the owning Telegram bot user may obtain their referral code."""
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT a.number FROM accounts a WHERE a.telegram_id=? AND NOT EXISTS(SELECT 1 FROM account_freezes f WHERE f.number=a.number)",(tid,)).fetchone()
        if not row:return None
        n=row["number"]
        code=c.execute("SELECT code FROM referral_codes WHERE number=?",(n,)).fetchone()
        if not code:
            while True:
                value=secrets.token_urlsafe(18)
                if c.execute("INSERT OR IGNORE INTO referral_codes(number,code) VALUES (?,?)",(n,value)).rowcount:break
            code={"code":value}
        stats=c.execute("SELECT COUNT(*) AS total,COALESCE(SUM(CASE WHEN rewarded_at>0 THEN 1 ELSE 0 END),0) AS completed,COALESCE(SUM(reward),0) AS earned FROM referrals WHERE inviter=?",(n,)).fetchone()
        wallet=c.execute("SELECT balance FROM wallets WHERE number=?",(n,)).fetchone()
        c.commit()
    return {"code":code["code"],"total":stats["total"],"completed":stats["completed"],"pending":stats["total"]-stats["completed"],"earned":stats["earned"],"balance":wallet["balance"] if wallet else 1000}

def issue(tid,referral_code=None):
    now = int(time.time())
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM accounts WHERE telegram_id=?", (tid,)).fetchone()
        if row and c.execute("SELECT 1 FROM account_freezes WHERE number=?",(row["number"],)).fetchone():
            c.rollback()
            return None
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
            # Only the first bot start can bind an invitation. Existing accounts
            # cannot be attributed retroactively, even after a number change.
            if isinstance(referral_code,str) and re.fullmatch(r"[A-Za-z0-9_-]{24}",referral_code):
                inviter=c.execute("SELECT r.number FROM referral_codes r JOIN accounts a ON a.number=r.number WHERE r.code=? AND a.telegram_id<>? AND NOT EXISTS(SELECT 1 FROM account_freezes f WHERE f.number=r.number)",(referral_code,tid)).fetchone()
                if inviter and inviter["number"]!=n:
                    c.execute("INSERT INTO referrals(invitee,inviter,created) VALUES (?,?,?)",(n,inviter["number"],now))
        code = f"{secrets.randbelow(1000000):06d}"
        c.execute("UPDATE accounts SET code_hash=?,expires=?,issued=?,attempts=0 WHERE telegram_id=?", (digest(n+":"+code),now+300,now,tid))
        c.commit()
        return n,code

def consume(n,code):
    now = int(time.time())
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM accounts WHERE number=?", (n,)).fetchone()
        if not row or c.execute("SELECT 1 FROM account_freezes WHERE number=?",(n,)).fetchone() or not row["code_hash"] or row["expires"]<=now or row["attempts"]>=5:
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
        first=c.execute("INSERT OR IGNORE INTO registrations VALUES (?,?)",(n,now)).rowcount
        if first:
            ref=c.execute("SELECT inviter FROM referrals WHERE invitee=? AND rewarded_at=0",(n,)).fetchone()
            if ref:
                inviter=ref["inviter"]
                # The successful code verification, ledger entry and wallet credit
                # are one transaction. A repeated login cannot pay again.
                paid=c.execute("UPDATE referrals SET rewarded_at=?,reward=? WHERE invitee=? AND rewarded_at=0",(now,REFERRAL_REWARD,n)).rowcount
                if paid:
                    c.execute("INSERT OR IGNORE INTO wallets(number) VALUES (?)",(inviter,))
                    before=c.execute("SELECT balance FROM wallets WHERE number=?",(inviter,)).fetchone()[0]
                    c.execute("UPDATE wallets SET balance=balance+? WHERE number=?",(REFERRAL_REWARD,inviter))
                    c.execute("INSERT INTO admin_user_actions(number,action,detail,reason,created) VALUES (?,?,?,?,?)",(inviter,"referral.reward",json.dumps({"delta":REFERRAL_REWARD,"before":before,"balance":before+REFERRAL_REWARD}),"Первый успешный вход приглашённого",now))
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
    bot_username=None
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
                command=cmd[0].split("@")[0].lower() if cmd else ""
                if command in ("/ref","/referral","/referrals","/invite"):
                    if not allow("referral_bot:"+str(sender["id"])):
                        continue
                    stats=referral_stats(sender["id"])
                    if not stats:
                        reply="Сначала создайте аккаунт Toxicgram через /start. Если аккаунт заморожен, обратитесь к администратору."
                    else:
                        if not bot_username:bot_username=api("getMe",{})["username"]
                        link=f"https://t.me/{bot_username}?start=ref_{stats['code']}"
                        reply=(f"🎁 Приглашай друзей в Toxicgram!\n\n"
                               f"За каждого нового пользователя, который впервые успешно войдёт в приложение, вы получите 500 Toxic Stars.\n\n"
                               f"Ваша ссылка:\n{link}\n\n"
                               f"Приглашений: {stats['total']}\n"
                               f"Ожидают регистрации: {stats['pending']}\n"
                               f"Зарегистрировались: {stats['completed']}\n"
                               f"Заработано: {stats['earned']} ⭐\n"
                               f"Баланс: {stats['balance']} ⭐\n\n"
                               f"Друг должен впервые открыть бота по вашей ссылке, получить код и войти в Toxicgram. Повторные входы не учитываются.")
                    # This message contains no login codes and may be forwarded.
                    api("sendMessage",{"chat_id":chat["id"],"text":reply})
                    continue
                if command in ("/start","/code","/number"):
                    prefix=None
                    if cmd[0].split("@")[0]=="/number":
                        if len(cmd)!=2 or cmd[1] not in ("+7","+1","+388"):
                            api("sendMessage",{"chat_id":chat["id"],"text":"Выберите виртуальный префикс: /number +7, /number +1 или /number +388. Это внутренние номера, не SIM-карты."})
                            continue
                        prefix=cmd[1]
                    ref_code=cmd[1][4:] if command=="/start" and len(cmd)==2 and cmd[1].startswith("ref_") else None
                    result=issue(sender["id"],ref_code)
                    if result:
                        n,code=result
                        phone=phone_for(n,prefix)
                        reply=f"Toxicgram\nВаш виртуальный номер: {phone}\nКод Toxicgram: {code}\nДействует 5 минут. Не пересылайте код.\nТолько для Toxicgram, не настоящий телефон.\nПрефикс: /number +7, /number +1, /number +388.\nСтарый ID: {n}\n\nПриглашай друзей: /ref — 500 Toxic Stars за первую регистрацию."
                    else:
                        with db() as conn:
                            frozen=conn.execute("SELECT 1 FROM account_freezes f JOIN accounts a ON a.number=f.number WHERE a.telegram_id=?",(sender["id"],)).fetchone()
                        reply="Ваш аккаунт Toxicgram заморожен. Обратитесь к администратору." if frozen else "Подождите 30 секунд перед запросом нового кода."
                else:
                    reply="Используйте /code для получения кода Toxicgram. /ref — ваша реферальная ссылка и статистика."
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
    number:str=Field(max_length=40)
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
        row=c.execute("SELECT s.number FROM sessions s WHERE s.token_hash=? AND s.expires>? AND NOT EXISTS(SELECT 1 FROM account_freezes f WHERE f.number=s.number)",(key,int(time.time()))).fetchone()
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
    recipient: str = Field(max_length=40)
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
        c.execute("INSERT INTO profile_names VALUES (?,?,?) ON CONFLICT(number) DO UPDATE SET first_name=excluded.first_name,last_name=excluded.last_name",(n,name,""))
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

class ProfilePatch(BaseModel):
    first_name:str|None=Field(default=None,max_length=64)
    last_name:str|None=Field(default=None,max_length=64)
    username:str|None=Field(default=None,max_length=32)
    bio:str|None=Field(default=None,max_length=160)

@app.put("/v1/profile/partial")
@app.patch("/v1/profile")
def patch_profile(body:ProfilePatch,request:Request):
    _,n=session(request)
    if body.username is not None and body.username and not re.fullmatch(r"[a-zA-Z0-9_]{5,32}",body.username): raise HTTPException(400,"Invalid username")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if body.first_name is not None or body.last_name is not None:
            old=c.execute("SELECT first_name,last_name FROM profile_names WHERE number=?",(n,)).fetchone()
            p=c.execute("SELECT name FROM profiles WHERE number=?",(n,)).fetchone()
            first=body.first_name.strip() if body.first_name is not None else old["first_name"] if old else p["name"] if p else n
            last=body.last_name.strip() if body.last_name is not None else old["last_name"] if old else ""
            if not first: raise HTTPException(400,"Empty name")
            c.execute("INSERT INTO profile_names VALUES (?,?,?) ON CONFLICT(number) DO UPDATE SET first_name=excluded.first_name,last_name=excluded.last_name",(n,first,last))
            c.execute("INSERT INTO profiles VALUES (?,?) ON CONFLICT(number) DO UPDATE SET name=excluded.name",(n,(first+" "+last).strip()))
        c.execute("INSERT OR IGNORE INTO profile_details(number) VALUES (?)",(n,))
        if body.username is not None:
            try:c.execute("UPDATE profile_details SET username=? WHERE number=?",(body.username.lower() or None,n))
            except sqlite3.IntegrityError:raise HTTPException(409,"Username taken")
        if body.bio is not None:c.execute("UPDATE profile_details SET bio=? WHERE number=?",(body.bio.strip(),n))
        c.commit()
    return public_profile(n)

@app.get("/v1/username/check")
def check_username(request:Request,username:str):
    _,n=session(request)
    if not re.fullmatch(r"[a-zA-Z0-9_]{5,32}",username):raise HTTPException(400,"Invalid username")
    with db() as c:
        occupied=c.execute("SELECT 1 FROM profile_details WHERE username=? COLLATE NOCASE AND number<>?",(username,n)).fetchone()
    return {"available":not bool(occupied)}

@app.get("/v1/users-search")
def users_search(request:Request,q:str):
    _,n=session(request)
    q=q.strip().lstrip("@")[:64].lower()
    if len(q)<2:return {"users":[]}
    if not allow("lookup:"+n):raise HTTPException(429,"Too many requests")
    with db() as c:
        rows=c.execute("""SELECT a.number FROM accounts a LEFT JOIN profiles p ON p.number=a.number LEFT JOIN profile_details d ON d.number=a.number LEFT JOIN phone_aliases ph ON ph.number=a.number WHERE a.number<>? AND (instr(lower(COALESCE(p.name,'')),?)>0 OR instr(lower(COALESCE(d.username,'')),?)>0 OR instr(COALESCE(ph.phone,''),?)>0) AND NOT EXISTS(SELECT 1 FROM blocks b WHERE (b.owner=? AND b.peer=a.number) OR (b.owner=a.number AND b.peer=?)) LIMIT 20""",(n,q,q,q,n,n)).fetchall()
    return {"users":[public_profile(x["number"]) for x in rows]}

@app.get("/v1/users/{number}")
def lookup(number:str,request:Request):
    _,n=session(request)
    if not allow("lookup:"+n):
        raise HTTPException(429,"Too many requests")
    peer=normalize_number(number)
    with db() as c:
        require_peer(c,peer)
        pass
    p=public_profile(peer)
    with db() as c:p.update(visible_presence(c,n,peer))
    return p

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
        p=public_profile(item["number"])
        item["phone"]=p["phone"]
        item["avatar"]=p["avatar"]
        item["first_name"]=p["first_name"]
        item["last_name"]=p["last_name"]
        item["username"]=p["username"]
        with db() as c:
            seen=visible_presence(c,n,item["number"])
        item.update(seen)
        if item["name"]==item["number"]: item["name"]=item["phone"]
        result.append(item)
    return {"chats":result}

def visible_presence(c,viewer,peer):
    # Exact presence is shared only with existing conversation partners, never blocked accounts.
    if viewer!=peer and (not c.execute("SELECT 1 FROM messages WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?) LIMIT 1",(viewer,peer,peer,viewer)).fetchone() or c.execute("SELECT 1 FROM blocks WHERE (owner=? AND peer=?) OR (owner=? AND peer=?)",(viewer,peer,peer,viewer)).fetchone()):
        return {"last_seen":0,"online_until":0}
    row=c.execute("SELECT last_seen FROM presence WHERE number=? AND NOT EXISTS(SELECT 1 FROM account_freezes WHERE number=?)",(peer,peer)).fetchone()
    seen=row["last_seen"] if row else 0
    return {"last_seen":seen,"online_until":seen+25 if seen else 0}

@app.get("/v1/sync")
def sync_messages(request:Request,after:int=0):
    _,n=session(request)
    if after<0:raise HTTPException(400,"Invalid cursor")
    now=int(time.time())
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO presence VALUES (?,?) ON CONFLICT(number) DO UPDATE SET last_seen=excluded.last_seen",(n,now))
        rows=c.execute("""SELECT m.id,m.sender,m.recipient,m.body AS text,m.created,COALESCE(e.edited,0) AS edited
          FROM messages m LEFT JOIN message_edits e ON e.message_id=m.id
          WHERE m.recipient=? AND m.sender<>? AND m.id>?
          AND NOT EXISTS(SELECT 1 FROM hidden_messages h WHERE h.owner=? AND h.message_id=m.id)
          AND (?<>0 OR m.id>COALESCE((SELECT rs.last_id FROM read_state rs WHERE rs.owner=? AND rs.peer=m.sender),0))
          ORDER BY m.id LIMIT 101""",(n,n,after,n,after,n)).fetchall()
        batch=rows[:100]
        cursor=batch[-1]["id"] if batch else max(after,c.execute("SELECT COALESCE(MAX(id),0) FROM messages WHERE recipient=?",(n,)).fetchone()[0])
        peers=c.execute("""SELECT peer,MAX(id) AS latest FROM (
          SELECT sender AS peer,id FROM messages WHERE recipient=? AND sender<>?
          UNION ALL SELECT recipient AS peer,id FROM messages WHERE sender=? AND recipient<>?)
          GROUP BY peer ORDER BY latest DESC LIMIT 100""",(n,n,n,n)).fetchall()
        numbers=set(x["peer"] for x in peers)|set(x["sender"] for x in batch)
        statuses=[]
        for peer in numbers:
            st=visible_presence(c,n,peer)
            read=c.execute("SELECT last_id FROM read_state WHERE owner=? AND peer=?",(peer,n)).fetchone()
            inbox=c.execute("SELECT last_id FROM read_state WHERE owner=? AND peer=?",(n,peer)).fetchone()
            statuses.append({"number":peer,**st,"read_outbox":read["last_id"] if read else 0,"read_inbox":inbox["last_id"] if inbox else 0})
        c.commit()
    profiles=[]
    for peer in set(x["sender"] for x in batch):
        p=public_profile(peer)
        st=next((x for x in statuses if x["number"]==peer),{})
        p.update(st);profiles.append(p)
    return {"messages":[dict(x) for x in batch],"users":profiles,"statuses":statuses,"cursor":cursor,"more":len(rows)>100,"server_time":now}

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
            attachment=c.execute("SELECT m.id,m.name,m.mime,m.size FROM media m JOIN message_media a ON a.media_id=m.id WHERE a.message_id=?",(item["id"],)).fetchone()
            item["attachment"]=dict(attachment) if attachment else None
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
        if c.execute("SELECT 1 FROM message_media WHERE message_id=?",(mid,)).fetchone(): raise HTTPException(400,"Cannot edit an attachment")
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
            c.execute("DELETE FROM media WHERE id IN (SELECT media_id FROM message_media WHERE message_id=?)",(mid,))
            c.execute("DELETE FROM message_media WHERE message_id=?",(mid,))
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
    about:str=Field(default="",max_length=255)
    mode:str=Field(default="basic",pattern=r"^(basic|channel)$")
    members:list[str]=Field(default_factory=list,max_length=100)

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
    members=set(normalize_number(x) for x in body.members)
    members.discard(n)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        for peer in members:
            require_peer(c,peer)
            if c.execute("SELECT 1 FROM blocks WHERE (owner=? AND peer=?) OR (owner=? AND peer=?)",(n,peer,peer,n)).fetchone():raise HTTPException(403,"Invitation unavailable")
        c.execute("INSERT INTO rooms VALUES (?,?,?,?)",(rid,n,title,body.kind))
        numeric=c.execute("INSERT INTO room_meta(room_id,about,mode,created) VALUES (?,?,?,?)",(rid,body.about,"channel" if body.kind=="channel" else body.mode,int(time.time()))).lastrowid
        c.execute("INSERT INTO room_members VALUES (?,?)",(rid,n))
        for peer in members:c.execute("INSERT INTO room_members VALUES (?,?)",(rid,peer))
        c.commit()
    return {"id":rid,"numeric_id":numeric,"title":title,"kind":body.kind,"owner":n,"mode":"channel" if body.kind=="channel" else body.mode,"about":body.about,"created":int(time.time()),"members":len(members)+1}

@app.get("/v1/rooms")
def list_rooms(request:Request):
    _,n=session(request)
    with db() as c:
        rows=c.execute("SELECT r.*, meta.numeric_id,meta.mode,meta.about,meta.created, (SELECT COUNT(*) FROM room_members x WHERE x.room_id=r.id) AS members FROM rooms r JOIN room_meta meta ON meta.room_id=r.id JOIN room_members m ON r.id=m.room_id WHERE m.number=? ORDER BY r.title COLLATE NOCASE LIMIT 100",(n,)).fetchall()
    return {"rooms":[dict(row) for row in rows]}

@app.get("/v1/rooms/by-id/{numeric}")
def room_by_id(numeric:int,request:Request):
    _,n=session(request)
    with db() as c:
        row=c.execute("SELECT r.*,meta.numeric_id,meta.mode,meta.about,meta.created,(SELECT COUNT(*) FROM room_members x WHERE x.room_id=r.id) AS members FROM rooms r JOIN room_meta meta ON meta.room_id=r.id JOIN room_members m ON m.room_id=r.id WHERE meta.numeric_id=? AND m.number=?",(numeric,n)).fetchone()
        if not row:raise HTTPException(404,"Room not found")
        members=c.execute("SELECT number FROM room_members WHERE room_id=? LIMIT 100",(row["id"],)).fetchall()
    return {"room":dict(row),"users":[public_profile(x["number"]) for x in members]}

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
def room_history(rid:str,request:Request,before:int=0):
    _,n=session(request)
    with db() as c:
        get_room(c,rid,n)
        rows=c.execute("SELECT m.id,m.sender,m.body AS text,m.created,COALESCE(p.name,m.sender) AS name FROM room_messages m LEFT JOIN profiles p ON p.number=m.sender WHERE m.room_id=? AND (?=0 OR m.id<?) ORDER BY m.id DESC LIMIT 100",(rid,before,before)).fetchall()
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
        created=int(time.time())
        mid=c.execute("INSERT INTO room_messages(room_id,sender,body,created) VALUES (?,?,?,?)",(rid,n,value,created)).lastrowid
        c.commit()
    return {"id":mid,"created":created}

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

MAX_MEDIA=8*1024*1024
MAX_AVATAR=512*1024
USER_STORAGE=32*1024*1024
TOTAL_STORAGE=250*1024*1024

async def read_limited(request,limit):
    chunks=bytearray()
    async for chunk in request.stream():
        if len(chunks)+len(chunk)>limit:
            raise HTTPException(413,"File too large")
        chunks.extend(chunk)
    if not chunks: raise HTTPException(400,"Empty file")
    return bytes(chunks)

def file_mime(raw,declared):
    if raw.startswith(b"\xff\xd8\xff"): return "image/jpeg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if len(raw)>12 and raw[:4]==b"RIFF" and raw[8:12]==b"WEBP": return "image/webp"
    if len(raw)>12 and raw[4:8]==b"ftyp": return "audio/mp4" if declared=="audio/mp4" else "video/mp4"
    if raw.startswith(b"OggS"): return "audio/ogg"
    if raw.startswith(b"%PDF-"): return "application/pdf"
    if raw.startswith(b"ID3"): return "audio/mpeg"
    return "application/octet-stream"

def store_media(c,n,name,mime,raw):
    own=c.execute("SELECT COALESCE(SUM(size),0) FROM media WHERE owner=?",(n,)).fetchone()[0]
    total=c.execute("SELECT COALESCE(SUM(size),0) FROM media").fetchone()[0]
    if own+len(raw)>USER_STORAGE or total+len(raw)>TOTAL_STORAGE:
        raise HTTPException(507,"Storage quota exceeded")
    mid=secrets.token_hex(16)
    c.execute("INSERT INTO media VALUES (?,?,?,?,?,?)",(mid,n,name,mime,raw,len(raw)))
    return mid

def put_attachment(n,peer,name,declared,raw):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        require_peer(c,peer)
        if c.execute("SELECT 1 FROM blocks WHERE (owner=? AND peer=?) OR (owner=? AND peer=?)",(n,peer,peer,n)).fetchone(): raise HTTPException(403,"Messaging unavailable")
        mime=file_mime(raw,declared)
        aid=store_media(c,n,name,mime,raw)
        mid=c.execute("INSERT INTO messages(sender,recipient,body,created) VALUES (?,?,?,?)",(n,peer,"📎 "+name,int(time.time()))).lastrowid
        c.execute("INSERT INTO message_media VALUES (?,?)",(mid,aid))
        c.commit()
    return {"id":mid,"attachment":aid}

@app.post("/v1/attachments")
async def upload_attachment(request:Request,recipient:str,name:str="file",mime:str="application/octet-stream"):
    _,n=await run_in_threadpool(session,request)
    if not await run_in_threadpool(allow,"upload:"+n): raise HTTPException(429,"Too many uploads")
    peer=await run_in_threadpool(normalize_number,recipient)
    name=re.sub(r"[\x00-\x1f/\\]","_",name.strip())[:120] or "file"
    raw=await read_limited(request,MAX_MEDIA)
    return await run_in_threadpool(put_attachment,n,peer,name,mime,raw)

def put_avatar(n,raw):
    mime=file_mime(raw,"")
    if mime not in ("image/jpeg","image/png","image/webp"): raise HTTPException(400,"Unsupported image")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("DELETE FROM media WHERE id IN (SELECT media_id FROM avatars WHERE number=?)",(n,))
        mid=store_media(c,n,"avatar",mime,raw)
        c.execute("INSERT INTO avatars VALUES (?,?) ON CONFLICT(number) DO UPDATE SET media_id=excluded.media_id",(n,mid))
        c.commit()
    return {"avatar":mid}

@app.put("/v1/avatar")
async def upload_avatar(request:Request):
    _,n=await run_in_threadpool(session,request)
    if not await run_in_threadpool(allow,"avatar:"+n): raise HTTPException(429,"Too many uploads")
    return await run_in_threadpool(put_avatar,n,await read_limited(request,MAX_AVATAR))

@app.get("/v1/media/{mid}")
def get_media(mid:str,request:Request):
    _,n=session(request)
    with db() as c:
        row=c.execute("""SELECT m.* FROM media m WHERE m.id=? AND
        (EXISTS(SELECT 1 FROM avatars a WHERE a.media_id=m.id) OR EXISTS(
         SELECT 1 FROM message_media a JOIN messages t ON t.id=a.message_id
         WHERE a.media_id=m.id AND (t.sender=? OR t.recipient=?)
         AND NOT EXISTS(SELECT 1 FROM hidden_messages h WHERE h.owner=? AND h.message_id=t.id)))""",(mid,n,n,n)).fetchone()
        if not row: raise HTTPException(404,"File not found")
        return Response(content=row["content"],media_type=row["mime"],headers={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff","Content-Disposition":"attachment"})

CATALOG={"heart":{"name":"Сердце","emoji":"💝","price":50},"bear":{"name":"Мишка","emoji":"🧸","price":100},"rose":{"name":"Роза","emoji":"🌹","price":75},"star":{"name":"Звезда","emoji":"🌟","price":150},"crystal":{"name":"Кристалл","emoji":"💎","price":250}}
CATALOG.update({"present":{"name":"Подарок","emoji":"🎁","price":100},"cake":{"name":"Торт","emoji":"🎂","price":120}})
GIFT_ART={"heart":"email_setup_heart","star":"star_reaction","crystal":"wallet_diamond_blue","present":"gift","cake":"cake"}
def seed_catalog(c):
    # Stable IDs 1..7 preserve legacy Android gift identifiers.
    c.execute("BEGIN IMMEDIATE")
    for index,(kind,item) in enumerate(CATALOG.items(),1):
        c.execute("INSERT OR IGNORE INTO catalog_gifts(id,kind,name,emoji,price,art) VALUES (?,?,?,?,?,?)",(index,kind,item["name"],item["emoji"],item["price"],GIFT_ART.get(kind,"")))
    art=Path(__file__).with_name("plush_pepe.json")
    if art.exists():
        data=gzip.compress(art.read_bytes(),mtime=0)
        asset=hashlib.sha256(data).hexdigest()
        c.execute("INSERT OR IGNORE INTO gift_art VALUES (?,?)",(asset,data))
        c.execute("INSERT OR IGNORE INTO catalog_gifts(kind,name,emoji,price,supply,rarity,upgrade_enabled,asset) VALUES (?,?,?,?,?,?,?,?)",("plush-pepe","Plush Pepe","🐸",500,1000,"legendary",1,asset))
        # Apply the requested redesign exactly once, preserving later Admin edits.
        c.execute("CREATE TABLE IF NOT EXISTS catalog_migrations (name TEXT PRIMARY KEY)")
        applied=c.execute("INSERT OR IGNORE INTO catalog_migrations VALUES (?)",("plush-pepe-art-v3",)).rowcount
        if applied:
            c.execute("UPDATE catalog_gifts SET asset=? WHERE kind=?", (asset,"plush-pepe"))
            c.execute("INSERT INTO admin_audit(action,kind,created) VALUES (?,?,?)",("artwork.redesign.v3","plush-pepe",int(time.time())))
    c.commit()

def catalog_item(row):
    d=dict(row)
    d["remaining"]=max(0,d["supply"]-d["issued"]) if d["supply"] else None
    d["gift_id"]=str(830000000000000000+d["id"]-1)
    return d

def catalog_rows(c,dynamic=False):
    return [catalog_item(x) for x in c.execute("SELECT * FROM catalog_gifts WHERE (?=1 OR id<=7) ORDER BY id",(int(dynamic),))]

ADMIN_KEY=os.getenv("TOXICGRAM_ADMIN_KEY","")
def admin_auth(request):
    scheme,_,value=request.headers.get("Authorization","").partition(" ")
    if len(ADMIN_KEY)<32: raise HTTPException(503,"Admin disabled")
    if scheme.lower()!="bearer" or len(value)>256 or not hmac.compare_digest(value.encode(),ADMIN_KEY.encode()):
        if not allow("admin:invalid"): raise HTTPException(429,"Too many attempts")
        raise HTTPException(401,"Unauthorized")

@app.get("/admin",response_class=HTMLResponse)
def admin_page():
    return HTMLResponse(Path(__file__).with_name("admin.html").read_text(encoding="utf-8"),headers={"Cache-Control":"no-store","Content-Security-Policy":"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data: blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'","X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer"})

@app.get("/admin/app.js")
def admin_js():
    return Response(Path(__file__).with_name("admin.js").read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})

@app.get("/admin/style.css")
def admin_css():
    return Response(Path(__file__).with_name("admin.css").read_text(encoding="utf-8"),media_type="text/css",headers={"X-Content-Type-Options":"nosniff"})

@app.get("/v1/admin/catalog")
def admin_catalog(request:Request):
    admin_auth(request)
    with db() as c:
        return {"catalog":catalog_rows(c,True),"stats":{"users":c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],"gifts":c.execute("SELECT COUNT(*) FROM gifts").fetchone()[0],"stars":c.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]}}


# Admin access is separate from ordinary user sessions. Never include bot IDs,
# login codes, access tokens, private messages or contact lists in the admin UI.
ADMIN_USER_SELECT = """
SELECT a.number, COALESCE(p.name,ph.phone,a.number) AS name,
       COALESCE(ph.phone,'') AS phone,COALESCE(pd.username,'') AS username,
       COALESCE(pd.bio,'') AS bio,COALESCE(av.media_id,'') AS avatar,
       COALESCE(w.balance,1000) AS balance,
       CASE WHEN f.number IS NULL THEN 0 ELSE 1 END AS frozen,
       COALESCE(f.reason,'') AS freeze_reason,COALESCE(f.created,0) AS frozen_at,
       (SELECT COUNT(*) FROM gifts g WHERE g.recipient=a.number) AS gift_count
FROM accounts a LEFT JOIN profiles p ON p.number=a.number
LEFT JOIN phone_aliases ph ON ph.number=a.number
LEFT JOIN profile_details pd ON pd.number=a.number
LEFT JOIN avatars av ON av.number=a.number
LEFT JOIN wallets w ON w.number=a.number
LEFT JOIN account_freezes f ON f.number=a.number
"""

@app.get("/v1/admin/users")
def admin_users(request:Request,q:str="",after:str="",limit:int=30):
    admin_auth(request)
    limit=max(1,min(100,limit))
    term=q.strip()[:100].lstrip("@").lower()
    with db() as c:
        rows=c.execute(ADMIN_USER_SELECT+"""
        WHERE a.number>? AND (?='' OR instr(lower(a.number),?)>0 OR
        instr(lower(COALESCE(p.name,'')),?)>0 OR
        instr(lower(COALESCE(pd.username,'')),?)>0 OR
        instr(COALESCE(ph.phone,''),?)>0)
        ORDER BY a.number LIMIT ?
        """,(after[:40],term,term,term,term,term,limit+1)).fetchall()
    return {"users":[dict(x) for x in rows[:limit]],"next":rows[limit-1]["number"] if len(rows)>limit else ""}

@app.get("/v1/admin/users/{number}")
def admin_user(number:str,request:Request):
    admin_auth(request)
    with db() as c:
        user=c.execute(ADMIN_USER_SELECT+" WHERE a.number=?",(number,)).fetchone()
        if not user: raise HTTPException(404,"Account not found")
        gifts=c.execute("""SELECT g.id,g.kind,g.serial,g.created,gn.num,
          COALESCE(cg.name,g.kind) AS name,COALESCE(cg.emoji,'') AS emoji,
          COALESCE(d.visible,0) AS visible
          FROM gifts g LEFT JOIN gift_numbers gn ON gn.gift_id=g.id
          LEFT JOIN catalog_gifts cg ON cg.kind=g.kind
          LEFT JOIN gift_details d ON d.gift_id=g.id
          WHERE g.recipient=? ORDER BY g.id DESC LIMIT 100""",(number,)).fetchall()
        audit=c.execute("SELECT action,detail,reason,created FROM admin_user_actions WHERE number=? ORDER BY id DESC LIMIT 50",(number,)).fetchall()
    return {"user":dict(user),"gifts":[dict(x) for x in gifts],"audit":[dict(x) for x in audit]}

@app.get("/v1/admin/users/{number}/avatar")
def admin_avatar(number:str,request:Request):
    admin_auth(request)
    with db() as c:
        row=c.execute("SELECT m.mime,m.content FROM avatars a JOIN media m ON m.id=a.media_id WHERE a.number=?",(number,)).fetchone()
    if not row or row["mime"] not in ("image/jpeg","image/png","image/webp"): raise HTTPException(404,"Avatar not found")
    return Response(row["content"],media_type=row["mime"],headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})

class AdminAction(BaseModel):
    request_id:str=Field(pattern=r"^[a-f0-9-]{16,64}$")
    reason:str=Field(min_length=1,max_length=250)

class AdminStars(AdminAction):
    delta:int=Field(ge=-100000000,le=100000000)

class AdminGift(AdminAction):
    kind:str=Field(min_length=1,max_length=24)

class AdminFreeze(AdminAction):
    frozen:bool

def admin_replay(c,number,action,body):
    sig=hashlib.sha256(json.dumps([number,action,body.model_dump()],sort_keys=True,separators=(",",":")).encode()).hexdigest()
    prev=c.execute("SELECT signature,result FROM admin_user_requests WHERE request_id=?",(body.request_id,)).fetchone()
    if prev and prev["signature"]!=sig: raise HTTPException(409,"Request ID already used")
    return sig,json.loads(prev["result"]) if prev else None

def admin_finish(c,number,action,body,sig,result):
    c.execute("INSERT INTO admin_user_actions(number,action,detail,reason,created) VALUES (?,?,?,?,?)",(number,action,json.dumps(result,ensure_ascii=False),body.reason.strip(),int(time.time())))
    c.execute("INSERT INTO admin_user_requests VALUES (?,?,?)",(body.request_id,sig,json.dumps(result,ensure_ascii=False)))
    c.commit()
    return result

@app.post("/v1/admin/users/{number}/stars")
def admin_stars(number:str,body:AdminStars,request:Request):
    admin_auth(request)
    if not body.delta or not body.reason.strip(): raise HTTPException(400,"Specify amount and reason")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        require_peer(c,number)
        sig,prev=admin_replay(c,number,"stars.adjust",body)
        if prev is not None: return prev
        c.execute("INSERT OR IGNORE INTO wallets(number) VALUES (?)",(number,))
        before=c.execute("SELECT balance FROM wallets WHERE number=?",(number,)).fetchone()[0]
        after=before+body.delta
        if not 0<=after<=1000000000: raise HTTPException(409,"Balance outside allowed range")
        c.execute("UPDATE wallets SET balance=? WHERE number=?",(after,number))
        return admin_finish(c,number,"stars.adjust",body,sig,{"ok":True,"before":before,"delta":body.delta,"balance":after})

@app.post("/v1/admin/users/{number}/gift")
def admin_grant_gift(number:str,body:AdminGift,request:Request):
    admin_auth(request)
    if not body.reason.strip(): raise HTTPException(400,"Specify reason")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        require_peer(c,number)
        sig,prev=admin_replay(c,number,"gift.grant",body)
        if prev is not None: return prev
        item=c.execute("SELECT * FROM catalog_gifts WHERE kind=?",(body.kind,)).fetchone()
        if not item: raise HTTPException(404,"Gift not found")
        if item["supply"] and item["issued"]>=item["supply"]: raise HTTPException(410,"Sold out")
        serial=secrets.token_hex(8)
        # No wallet debit; the administrative sender is intentionally anonymous.
        gid=c.execute("INSERT INTO gifts(sender,recipient,kind,created,serial) VALUES (?,?,?,?,?)",("ADMIN",number,body.kind,int(time.time()),serial)).lastrowid
        num=item["issued"]+1
        c.execute("UPDATE catalog_gifts SET issued=issued+1 WHERE id=?",(item["id"],))
        c.execute("INSERT INTO gift_numbers VALUES (?,?)",(gid,num))
        c.execute("INSERT INTO gift_details(gift_id,visible,anonymous,message) VALUES (?,0,1,?)",(gid,"Toxicgram"))
        return admin_finish(c,number,"gift.grant",body,sig,{"ok":True,"kind":body.kind,"gift_id":gid,"serial":serial,"num":num})

@app.post("/v1/admin/users/{number}/freeze")
def admin_freeze(number:str,body:AdminFreeze,request:Request):
    admin_auth(request)
    if not body.reason.strip(): raise HTTPException(400,"Specify reason")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        require_peer(c,number)
        action="account.freeze" if body.frozen else "account.unfreeze"
        sig,prev=admin_replay(c,number,action,body)
        if prev is not None: return prev
        if body.frozen:
            c.execute("INSERT INTO account_freezes VALUES (?,?,?) ON CONFLICT(number) DO UPDATE SET reason=excluded.reason,created=excluded.created",(number,body.reason.strip(),int(time.time())))
            c.execute("DELETE FROM sessions WHERE number=?",(number,))
            c.execute("UPDATE accounts SET code_hash=NULL,expires=0,attempts=0 WHERE number=?",(number,))
        else:
            c.execute("DELETE FROM account_freezes WHERE number=?",(number,))
            # A fresh login is required after unfreezing.
            c.execute("UPDATE accounts SET issued=0 WHERE number=?",(number,))
        return admin_finish(c,number,action,body,sig,{"ok":True,"frozen":body.frozen})

class CatalogEdit(BaseModel):
    kind:str=Field(pattern=r"^[a-z0-9][a-z0-9-]{0,23}$")
    name:str=Field(min_length=1,max_length=64)
    emoji:str=Field(default="",max_length=16)
    price:int=Field(ge=1,le=100000000)
    supply:int=Field(default=0,ge=0,le=100000000)
    rarity:str=Field(default="common",pattern=r"^(common|rare|epic|legendary)$")
    upgrade_enabled:bool=False
    active:bool=True
    asset:str=Field(default="",pattern=r"^(|[a-f0-9]{64})$")

@app.put("/v1/admin/catalog")
def edit_catalog(body:CatalogEdit,request:Request):
    admin_auth(request)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        old=c.execute("SELECT * FROM catalog_gifts WHERE kind=?",(body.kind,)).fetchone()
        if not old and c.execute("SELECT COUNT(*) FROM catalog_gifts").fetchone()[0]>=200: raise HTTPException(409,"Catalog limit")
        if body.asset and not c.execute("SELECT 1 FROM gift_art WHERE id=?",(body.asset,)).fetchone(): raise HTTPException(400,"Unknown artwork")
        if not body.asset and (not old or not old["art"]) and body.active: raise HTTPException(400,"Artwork required")
        if old and body.supply and body.supply<old["issued"]: raise HTTPException(409,"Supply below issued count")
        if old:
            c.execute("UPDATE catalog_gifts SET name=?,emoji=?,price=?,supply=?,rarity=?,upgrade_enabled=?,active=?,asset=? WHERE kind=?",(body.name,body.emoji,body.price,body.supply,body.rarity,int(body.upgrade_enabled),int(body.active),body.asset,body.kind))
        else:
            c.execute("INSERT INTO catalog_gifts(kind,name,emoji,price,supply,rarity,upgrade_enabled,active,asset) VALUES (?,?,?,?,?,?,?,?,?)",(body.kind,body.name,body.emoji,body.price,body.supply,body.rarity,int(body.upgrade_enabled),int(body.active),body.asset))
        c.execute("INSERT INTO admin_audit(action,kind,created) VALUES (?,?,?)",("catalog.update",body.kind,int(time.time())))
        c.commit()
    return {"ok":True}

@app.post("/v1/admin/art")
async def upload_gift_art(request:Request):
    admin_auth(request)
    raw=await read_limited(request,256*1024)
    try:
        if raw[:2]==b"\x1f\x8b":
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f: raw=f.read(1024*1024+1)
        if len(raw)>1024*1024: raise ValueError()
        obj=json.loads(raw)
        if not isinstance(obj,dict) or obj.get("w")!=512 or obj.get("h")!=512 or not 1<=obj.get("fr",0)<=60 or not 0<obj.get("op",0)-obj.get("ip",0)<=180 or not isinstance(obj.get("layers"),list) or not 1<=len(obj["layers"])<=100 or obj.get("assets"): raise ValueError()
        # Only self-contained vector animations; no external resources or expression strings.
        def check(x,depth=0):
            if depth>40: raise ValueError()
            if isinstance(x,dict):
                if x.get("ty")==2 or "u" in x or "x" in x and isinstance(x["x"],str): raise ValueError()
                for v in x.values(): check(v,depth+1)
            elif isinstance(x,list):
                for v in x: check(v,depth+1)
        check(obj)
        data=gzip.compress(json.dumps(obj,separators=(",",":"),allow_nan=False).encode(),mtime=0)
        if len(data)>256*1024: raise ValueError()
    except Exception: raise HTTPException(400,"Use self-contained 512x512 vector Lottie JSON or TGS, maximum 180 frames")
    asset=hashlib.sha256(data).hexdigest()
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT COALESCE(SUM(length(data)),0) FROM gift_art").fetchone()[0]+len(data)>32*1024*1024: raise HTTPException(409,"Artwork storage limit")
        c.execute("INSERT OR IGNORE INTO gift_art VALUES (?,?)",(asset,data))
        c.commit()
    return {"asset":asset}

@app.get("/v1/gift-art/{asset}")
def gift_art(asset:str):
    if not re.fullmatch(r"[a-f0-9]{64}",asset): raise HTTPException(404)
    with db() as c:
        row=c.execute("SELECT data FROM gift_art WHERE id=? AND EXISTS(SELECT 1 FROM catalog_gifts WHERE asset=?)",(asset,asset)).fetchone()
    if not row: raise HTTPException(404)
    return Response(row["data"],media_type="application/x-tgsticker",headers={"Cache-Control":"public,max-age=31536000,immutable","X-Content-Type-Options":"nosniff"})

class GiftSend(BaseModel):
    recipient:str=Field(max_length=40)
    kind:str=Field(max_length=24)
    request_id:str=Field(default="",max_length=80)
    anonymous:bool=False
    message:str=Field(default="",max_length=250)
    expected_price:int|None=Field(default=None,ge=1)

def gift_row(row,own):
    item=dict(row)
    if item.get("anonymous") or not own: item.pop("sender",None)
    return item

@app.get("/v1/users/{number}/gifts")
def profile_gifts(number:str,request:Request):
    _,n=session(request);peer=normalize_number(number)
    with db() as c:
        require_peer(c,peer)
        if peer!=n and c.execute("SELECT 1 FROM blocks WHERE (owner=? AND peer=?) OR (owner=? AND peer=?)",(n,peer,peer,n)).fetchone(): raise HTTPException(403,"Gift collection unavailable")
        rows=c.execute("""SELECT g.id,g.kind,g.serial,g.created,g.sender,COALESCE(d.visible,0) AS visible,
        COALESCE(d.anonymous,0) AS anonymous,COALESCE(d.message,'') AS message,gn.num AS num FROM gifts g LEFT JOIN gift_numbers gn ON gn.gift_id=g.id
        LEFT JOIN gift_details d ON d.gift_id=g.id WHERE g.recipient=? AND (?=1 OR d.visible=1)
        ORDER BY g.id DESC LIMIT 100""",(peer,int(peer==n))).fetchall()
    return {"received":[gift_row(x,peer==n) for x in rows]}

class GiftVisibility(BaseModel):
    visible:bool

@app.put("/v1/gifts/{gid}/visibility")
def gift_visibility(gid:int,body:GiftVisibility,request:Request):
    _,n=session(request)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if not c.execute("SELECT 1 FROM gifts WHERE id=? AND recipient=?",(gid,n)).fetchone(): raise HTTPException(404,"Gift not found")
        c.execute("INSERT INTO gift_details(gift_id,visible) VALUES (?,?) ON CONFLICT(gift_id) DO UPDATE SET visible=excluded.visible",(gid,int(body.visible)))
        c.commit()
    return {"ok":True}

@app.get("/v1/gifts")
def gift_catalog(request:Request,dynamic:bool=False):
    _,n=session(request)
    with db() as c:
        c.execute("INSERT OR IGNORE INTO wallets(number) VALUES (?)",(n,))
        balance=c.execute("SELECT balance FROM wallets WHERE number=?",(n,)).fetchone()[0]
        rows=c.execute("SELECT id,kind,serial,created FROM gifts WHERE recipient=? ORDER BY id DESC LIMIT 100",(n,)).fetchall()
        catalog=catalog_rows(c,dynamic)
    return {"balance":balance,"catalog":catalog,"received":[dict(x) for x in rows]}

@app.post("/v1/gifts")
def send_gift(body:GiftSend,request:Request):
    _,n=session(request)
    peer=normalize_number(body.recipient)
    if not allow("gift:"+n): raise HTTPException(429,"Too many requests")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        require_peer(c,peer)
        if body.request_id:
            prior=c.execute("SELECT g.serial,g.kind,g.recipient FROM gift_orders o JOIN gifts g ON g.id=o.gift_id WHERE o.sender=? AND o.request_id=?",(n,body.request_id)).fetchone()
            if prior:
                if prior["kind"]!=body.kind or prior["recipient"]!=peer: raise HTTPException(409,"Order mismatch")
                c.commit()
                return {"serial":prior["serial"]}
        item=c.execute("SELECT * FROM catalog_gifts WHERE kind=?",(body.kind,)).fetchone()
        if not item or not item["active"]: raise HTTPException(400,"Gift unavailable")
        if body.expected_price is not None and body.expected_price!=item["price"]: raise HTTPException(412,"Price changed")
        if item["supply"] and item["issued"]>=item["supply"]: raise HTTPException(410,"Sold out")
        if c.execute("SELECT 1 FROM blocks WHERE (owner=? AND peer=?) OR (owner=? AND peer=?)",(n,peer,peer,n)).fetchone(): raise HTTPException(403,"Gift unavailable")
        c.execute("INSERT OR IGNORE INTO wallets(number) VALUES (?)",(n,))
        changed=c.execute("UPDATE wallets SET balance=balance-? WHERE number=? AND balance>=?",(item["price"],n,item["price"])).rowcount
        if not changed: raise HTTPException(409,"Not enough demo stars")
        serial=secrets.token_hex(8)
        gid=c.execute("INSERT INTO gifts(sender,recipient,kind,created,serial) VALUES (?,?,?,?,?)",(n,peer,body.kind,int(time.time()),serial)).lastrowid
        c.execute("UPDATE catalog_gifts SET issued=issued+1 WHERE id=?",(item["id"],))
        c.execute("INSERT INTO gift_numbers VALUES (?,?)",(gid,item["issued"]+1))
        c.execute("INSERT INTO gift_details(gift_id,visible,anonymous,message) VALUES (?,?,?,?)",(gid,0,int(body.anonymous),body.message.strip()))
        if body.request_id: c.execute("INSERT INTO gift_orders VALUES (?,?,?)",(n,body.request_id,gid))
        c.commit()
    return {"serial":serial}

class StoryCreate(BaseModel):
    text:str=Field(min_length=1,max_length=280)

@app.get("/v1/stories")
def get_stories(request:Request):
    _,n=session(request)
    with db() as c:
        c.execute("DELETE FROM stories WHERE created<=?",(int(time.time())-86400,))
        rows=c.execute("""SELECT s.*,COALESCE(p.name,s.owner) AS name FROM stories s LEFT JOIN profiles p ON p.number=s.owner
          WHERE s.owner=? OR (EXISTS(SELECT 1 FROM messages m WHERE (m.sender=s.owner AND m.recipient=?) OR (m.sender=? AND m.recipient=s.owner))
          AND NOT EXISTS(SELECT 1 FROM blocks b WHERE (b.owner=? AND b.peer=s.owner) OR (b.owner=s.owner AND b.peer=?)))
          ORDER BY s.id DESC LIMIT 100""",(n,n,n,n,n)).fetchall()
    return {"stories":[dict(x) for x in rows]}

@app.post("/v1/stories")
def new_story(body:StoryCreate,request:Request):
    _,n=session(request)
    if not allow("story:"+n): raise HTTPException(429,"Too many requests")
    value=body.text.strip()
    if not value: raise HTTPException(400,"Empty story")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("DELETE FROM stories WHERE created<=?",(int(time.time())-86400,))
        if c.execute("SELECT COUNT(*) FROM stories WHERE owner=?",(n,)).fetchone()[0]>=10: raise HTTPException(429,"Story limit")
        mid=c.execute("INSERT INTO stories(owner,text,created) VALUES (?,?,?)",(n,value,int(time.time()))).lastrowid
        c.commit()
    return {"id":mid}

@app.delete("/v1/stories/{mid}")
def delete_story(mid:int,request:Request):
    _,n=session(request)
    with db() as c:
        if not c.execute("DELETE FROM stories WHERE id=? AND owner=?",(mid,n)).rowcount: raise HTTPException(404,"Story not found")
    return {"ok":True}
