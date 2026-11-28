import hashlib, hmac, json, os, re, secrets, sqlite3, threading, time, urllib.request
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.concurrency import run_in_threadpool
import base64, binascii, gzip, io
from datetime import datetime, timezone
import calendar
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
        CREATE TABLE IF NOT EXISTS bots (number TEXT PRIMARY KEY, owner TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1);
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
        CREATE TABLE IF NOT EXISTS room_message_media (message_id INTEGER PRIMARY KEY, media_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS room_attachment_orders (sender TEXT NOT NULL, request_id TEXT NOT NULL, message_id INTEGER NOT NULL, signature TEXT NOT NULL, PRIMARY KEY(sender,request_id));
        CREATE TABLE IF NOT EXISTS attachment_details (media_id TEXT PRIMARY KEY, kind TEXT NOT NULL, duration INTEGER NOT NULL DEFAULT 0, width INTEGER NOT NULL DEFAULT 0, height INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS attachment_orders (sender TEXT NOT NULL, request_id TEXT NOT NULL, message_id INTEGER NOT NULL, signature TEXT NOT NULL, PRIMARY KEY(sender,request_id));
        CREATE TABLE IF NOT EXISTS message_media (message_id INTEGER PRIMARY KEY, media_id TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS avatars (number TEXT PRIMARY KEY, media_id TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS premium_subscriptions (number TEXT PRIMARY KEY, months INTEGER NOT NULL, price INTEGER NOT NULL, started INTEGER NOT NULL, paid_months INTEGER NOT NULL, paid_until INTEGER NOT NULL, renew INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS premium_orders (number TEXT NOT NULL, request_id TEXT NOT NULL, months INTEGER NOT NULL, PRIMARY KEY(number,request_id));
        CREATE TABLE IF NOT EXISTS wallets (number TEXT PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 1000);
        CREATE TABLE IF NOT EXISTS gifts (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL, recipient TEXT NOT NULL, kind TEXT NOT NULL, created INTEGER NOT NULL, serial TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS gift_details (gift_id INTEGER PRIMARY KEY, visible INTEGER NOT NULL DEFAULT 0, anonymous INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS gift_receipts (message_id INTEGER PRIMARY KEY, gift_id INTEGER NOT NULL, price INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS gift_orders (sender TEXT NOT NULL, request_id TEXT NOT NULL, gift_id INTEGER NOT NULL, PRIMARY KEY(sender,request_id));
        CREATE TABLE IF NOT EXISTS catalog_gifts (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT UNIQUE NOT NULL, name TEXT NOT NULL, emoji TEXT NOT NULL DEFAULT '', price INTEGER NOT NULL, supply INTEGER NOT NULL DEFAULT 0, issued INTEGER NOT NULL DEFAULT 0, rarity TEXT NOT NULL DEFAULT 'common', upgrade_enabled INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, art TEXT NOT NULL DEFAULT '', asset TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS gift_art (id TEXT PRIMARY KEY, data BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS gift_numbers (gift_id INTEGER PRIMARY KEY, num INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS user_verifications (number TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, symbol INTEGER NOT NULL, color INTEGER NOT NULL);
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

def public_profile(n,own=False):
    phone=phone_for(n)
    with db() as c:
        row=c.execute("SELECT name FROM profiles WHERE number=?",(n,)).fetchone()
        details=c.execute("SELECT username,bio FROM profile_details WHERE number=?",(n,)).fetchone()
        avatar=c.execute("SELECT media_id FROM avatars WHERE number=?",(n,)).fetchone()
        names=c.execute("SELECT first_name,last_name FROM profile_names WHERE number=?",(n,)).fetchone()
        gift_count=c.execute("SELECT COUNT(*) FROM gifts g LEFT JOIN gift_details d ON g.id=d.gift_id WHERE g.recipient=? AND (?=1 OR d.visible=1)",(n,int(own))).fetchone()[0]
        premium=c.execute("SELECT 1 FROM premium_subscriptions WHERE number=? AND paid_until>?",(n,int(time.time()))).fetchone() is not None
        verification=c.execute("SELECT title,description,symbol,color FROM user_verifications WHERE number=?",(n,)).fetchone()
    return {"verification":dict(verification) if verification else None,"premium":premium,"first_name":names["first_name"] if names else (row["name"] if row else phone),"last_name":names["last_name"] if names else "","gift_count":gift_count,"avatar":avatar["media_id"] if avatar else "","number":n,"phone":phone,"name":row["name"] if row else phone,"username":(details["username"] or "") if details else "","bio":details["bio"] if details else ""}

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
                if not c.execute("SELECT 1 FROM accounts WHERE number=? UNION SELECT 1 FROM bots WHERE number=?", (n,n)).fetchone():
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

def allow(key,maximum=30):
    w = int(time.time())//60
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("DELETE FROM limits WHERE window<?", (w-1,))
        c.execute("INSERT INTO limits VALUES (?,?,1) ON CONFLICT(key) DO UPDATE SET count=CASE WHEN window=excluded.window THEN count+1 ELSE 1 END,window=excluded.window", (key,w))
        count = c.execute("SELECT count FROM limits WHERE key=?", (key,)).fetchone()[0]
        c.commit()
        return count<=maximum

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
    threading.Thread(target=premium_worker,args=(stop,),daemon=True).start()
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
    return public_profile(session(request)[1],own=True)

PREMIUM_PLANS={1:1499,12:899,24:499}

def premium_boundary(start,months):
    d=datetime.fromtimestamp(start,timezone.utc)
    index=d.year*12+d.month-1+months
    year,month=divmod(index,12)
    return int(d.replace(year=year,month=month+1,day=min(d.day,calendar.monthrange(year,month+1)[1])).timestamp())

def premium_renew(c,now):
    rows=c.execute("SELECT * FROM premium_subscriptions WHERE renew=1 AND paid_until<=?",(now,)).fetchall()
    for row in rows:
        n=row["number"]
        # No retroactive charges after outages, cancellation or insufficient funds.
        if row["paid_months"]>=row["months"] or premium_boundary(row["started"],row["paid_months"]+1)<=now or c.execute("SELECT 1 FROM account_freezes WHERE number=?",(n,)).fetchone():
            c.execute("UPDATE premium_subscriptions SET renew=0 WHERE number=?",(n,))
            continue
        if not c.execute("UPDATE wallets SET balance=balance-? WHERE number=? AND balance>=?",(row["price"],n,row["price"])).rowcount:
            c.execute("UPDATE premium_subscriptions SET renew=0 WHERE number=?",(n,))
            continue
        paid=row["paid_months"]+1
        c.execute("UPDATE premium_subscriptions SET paid_months=?,paid_until=?,renew=? WHERE number=?",(paid,premium_boundary(row["started"],paid),int(paid<row["months"]),n))

def premium_worker(stop):
    while not stop.is_set():
        try:
            with db() as c:
                c.execute("BEGIN IMMEDIATE")
                premium_renew(c,int(time.time()))
                c.commit()
        except Exception:
            print("Premium billing check failed",flush=True)
        stop.wait(60)

def premium_status(c,n):
    row=c.execute("SELECT * FROM premium_subscriptions WHERE number=?",(n,)).fetchone()
    wallet=c.execute("SELECT balance FROM wallets WHERE number=?",(n,)).fetchone()
    result=dict(row) if row else {}
    result.pop("number",None)
    result["active"]=bool(row and row["paid_until"]>int(time.time()))
    result["balance"]=wallet["balance"] if wallet else 1000
    return result

class PremiumPurchase(BaseModel):
    months:int
    request_id:str=Field(min_length=16,max_length=80)

@app.get("/v1/premium")
def get_premium(request:Request):
    _,n=session(request)
    with db() as c:
        return premium_status(c,n)

@app.post("/v1/premium")
def buy_premium(body:PremiumPurchase,request:Request):
    _,n=session(request)
    price=PREMIUM_PLANS.get(body.months)
    if price is None: raise HTTPException(400,"Invalid plan")
    now=int(time.time())
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        prior=c.execute("SELECT months FROM premium_orders WHERE number=? AND request_id=?",(n,body.request_id)).fetchone()
        if prior:
            if prior["months"]!=body.months: raise HTTPException(409,"Order mismatch")
            return premium_status(c,n)
        if premium_status(c,n)["active"]: raise HTTPException(409,"Premium already active")
        c.execute("INSERT OR IGNORE INTO wallets(number) VALUES (?)",(n,))
        if not c.execute("UPDATE wallets SET balance=balance-? WHERE number=? AND balance>=?",(price,n,price)).rowcount:
            raise HTTPException(409,"Insufficient stars")
        c.execute("INSERT OR REPLACE INTO premium_subscriptions VALUES (?,?,?,?,?,?,?)",(n,body.months,price,now,1,premium_boundary(now,1),int(body.months>1)))
        c.execute("INSERT INTO premium_orders VALUES (?,?,?)",(n,body.request_id,body.months))
        c.commit()
        return premium_status(c,n)

@app.post("/v1/premium/cancel")
def cancel_premium(request:Request):
    _,n=session(request)
    with db() as c:
        c.execute("UPDATE premium_subscriptions SET renew=0 WHERE number=?",(n,))
        return premium_status(c,n)

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
    if not c.execute("SELECT 1 FROM accounts WHERE number=? UNION SELECT 1 FROM bots WHERE number=? AND active=1",(number,number)).fetchone():
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
        rows=c.execute("""SELECT a.number FROM (SELECT number FROM accounts UNION SELECT number FROM bots WHERE active=1) a LEFT JOIN profiles p ON p.number=a.number LEFT JOIN profile_details d ON d.number=a.number LEFT JOIN phone_aliases ph ON ph.number=a.number WHERE a.number<>? AND (instr(lower(COALESCE(p.name,'')),?)>0 OR instr(lower(COALESCE(d.username,'')),?)>0 OR instr(COALESCE(ph.phone,''),?)>0) AND NOT EXISTS(SELECT 1 FROM blocks b WHERE (b.owner=? AND b.peer=a.number) OR (b.owner=a.number AND b.peer=?)) LIMIT 20""",(n,q,q,q,n,n)).fetchall()
    return {"users":[public_profile(x["number"]) for x in rows]}

@app.get("/v1/users/{number}")
def lookup(number:str,request:Request):
    _,n=session(request)
    if not allow("profile-read:"+n,180):
        raise HTTPException(429,"Too many requests")
    peer=normalize_number(number)
    with db() as c:
        require_peer(c,peer)
        pass
    p=public_profile(peer,own=peer==n)
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
        item["premium"]=p["premium"]
        item["verification"]=p["verification"]
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
    delivered=[]
    with db() as c:
        for row in batch:
            item=dict(row)
            attachment=c.execute("SELECT m.id,m.name,m.mime,m.size,COALESCE(d.kind,'file') AS kind,COALESCE(d.duration,0) AS duration,COALESCE(d.width,0) AS width,COALESCE(d.height,0) AS height FROM media m JOIN message_media a ON a.media_id=m.id LEFT JOIN attachment_details d ON d.media_id=m.id WHERE a.message_id=?",(item["id"],)).fetchone()
            item["attachment"]=dict(attachment) if attachment else None
            item["gift"]=gift_receipt(c,item["id"])
            delivered.append(item)
    profiles=[]
    for peer in set(x["sender"] for x in batch):
        p=public_profile(peer)
        st=next((x for x in statuses if x["number"]==peer),{})
        p.update(st);profiles.append(p)
    return {"messages":delivered,"users":profiles,"statuses":statuses,"cursor":cursor,"more":len(rows)>100,"server_time":now}

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
            attachment=c.execute("SELECT m.id,m.name,m.mime,m.size,COALESCE(d.kind,'file') AS kind,COALESCE(d.duration,0) AS duration,COALESCE(d.width,0) AS width,COALESCE(d.height,0) AS height FROM media m JOIN message_media a ON a.media_id=m.id LEFT JOIN attachment_details d ON d.media_id=m.id WHERE a.message_id=?",(item["id"],)).fetchone()
            item["attachment"]=dict(attachment) if attachment else None
            item["gift"]=gift_receipt(c,item["id"])
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

@app.get("/v1/rooms/sync")
def sync_rooms(request:Request,after:int=0):
    _,n=session(request)
    if after<0: raise HTTPException(400,"Invalid cursor")
    with db() as c:
        rows=c.execute("""SELECT m.id,m.sender,m.body AS text,m.created,m.room_id
            FROM room_messages m JOIN room_members member ON member.room_id=m.room_id
            WHERE member.number=? AND m.id>? ORDER BY m.id LIMIT 101""",(n,after)).fetchall()
        batch=rows[:100]
        rooms=c.execute("""SELECT r.*,meta.numeric_id,meta.mode,meta.about,meta.created,
            (SELECT COUNT(*) FROM room_members x WHERE x.room_id=r.id) AS members
            FROM rooms r JOIN room_meta meta ON meta.room_id=r.id
            JOIN room_members member ON member.room_id=r.id WHERE member.number=?""",(n,)).fetchall()
        cursor=batch[-1]["id"] if batch else after
    with db() as c:
        delivered=[room_media_item(c,x) for x in batch]
    return {"messages":delivered,"rooms":[dict(x) for x in rooms],
            "users":[public_profile(peer,own=peer==n) for peer in {x["sender"] for x in batch}],
            "cursor":cursor,"more":len(rows)>100}

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
        delivered=[room_media_item(c,row) for row in reversed(rows)]
    return {"messages":delivered}

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

MAX_MEDIA=24*1024*1024
MAX_AVATAR=512*1024
USER_STORAGE=64*1024*1024
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

def put_attachment(n,peer,name,declared,raw,kind="file",duration=0,width=0,height=0,request_id="",caption=""):
    signature=hashlib.sha256(raw).hexdigest()+":"+peer+":"+kind+":"+name+":"+str(duration)+":"+str(width)+":"+str(height)+":"+caption
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        require_peer(c,peer)
        if c.execute("SELECT 1 FROM blocks WHERE (owner=? AND peer=?) OR (owner=? AND peer=?)",(n,peer,peer,n)).fetchone(): raise HTTPException(403,"Messaging unavailable")
        if request_id:
            previous=c.execute("SELECT o.signature,m.id,m.created,a.media_id FROM attachment_orders o JOIN messages m ON m.id=o.message_id JOIN message_media a ON a.message_id=m.id WHERE o.sender=? AND o.request_id=?",(n,request_id)).fetchone()
            if previous:
                if previous["signature"]!=signature:raise HTTPException(409,"Upload request mismatch")
                return {"id":previous["id"],"attachment":previous["media_id"],"created":previous["created"]}
            if c.execute("SELECT 1 FROM attachment_orders WHERE sender=? AND request_id=?",(n,request_id)).fetchone():raise HTTPException(409,"Upload already used")
        mime=file_mime(raw,declared)
        if kind=="voice" and mime not in ("audio/ogg","audio/mp4","audio/mpeg"):raise HTTPException(400,"Invalid voice message")
        if kind in ("round","video") and mime!="video/mp4":raise HTTPException(400,"Invalid video message")
        if kind=="photo" and mime not in ("image/jpeg","image/png","image/webp"):raise HTTPException(400,"Invalid photo")
        aid=store_media(c,n,name,mime,raw)
        created=int(time.time())
        mid=c.execute("INSERT INTO messages(sender,recipient,body,created) VALUES (?,?,?,?)",(n,peer,caption if kind in ("voice","round","photo","video") else caption or "📎 "+name,created)).lastrowid
        c.execute("INSERT INTO message_media VALUES (?,?)",(mid,aid))
        c.execute("INSERT INTO attachment_details VALUES (?,?,?,?,?)",(aid,kind,duration,width,height))
        if request_id:c.execute("INSERT INTO attachment_orders VALUES (?,?,?,?)",(n,request_id,mid,signature))
        c.commit()
    return {"id":mid,"attachment":aid,"created":created}

@app.post("/v1/attachments")
async def upload_attachment(request:Request,recipient:str,name:str="file",mime:str="application/octet-stream",kind:str="file",duration:int=0,width:int=0,height:int=0,request_id:str="",caption:str=""):
    if kind not in ("file","voice","round","photo","video") or not 0<=duration<=3600 or not 0<=width<=4096 or not 0<=height<=4096 or len(caption)>1024 or (request_id and not re.fullmatch(r"-?[0-9]{1,20}",request_id)):raise HTTPException(400,"Invalid attachment metadata")
    _,n=await run_in_threadpool(session,request)
    if not await run_in_threadpool(allow,"upload:"+n): raise HTTPException(429,"Too many uploads")
    peer=await run_in_threadpool(normalize_number,recipient)
    name=re.sub(r"[\x00-\x1f/\\]","_",name.strip())[:120] or "file"
    raw=await read_limited(request,MAX_MEDIA)
    return await run_in_threadpool(put_attachment,n,peer,name,mime,raw,kind,duration,width,height,request_id,caption)

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

def room_media_item(c,row):
    item=dict(row)
    attachment=c.execute("""SELECT m.id,m.name,m.mime,m.size,d.kind,d.duration,d.width,d.height
        FROM room_message_media a JOIN media m ON m.id=a.media_id
        JOIN attachment_details d ON d.media_id=m.id WHERE a.message_id=?""",(item["id"],)).fetchone()
    item["attachment"]=dict(attachment) if attachment else None
    return item

def put_room_attachment(n,rid,name,declared,raw,kind,duration,width,height,request_id,caption):
    signature=hashlib.sha256(raw).hexdigest()+":"+json.dumps([rid,name,kind,duration,width,height,caption])
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        room=get_room(c,rid,n)
        if room["kind"]=="channel" and room["owner"]!=n: raise HTTPException(403,"Only owner can post")
        if request_id:
            prior=c.execute("""SELECT o.signature,m.id,m.created,a.media_id FROM room_attachment_orders o
                JOIN room_messages m ON m.id=o.message_id JOIN room_message_media a ON a.message_id=m.id
                WHERE o.sender=? AND o.request_id=?""",(n,request_id)).fetchone()
            if prior:
                if prior["signature"]!=signature: raise HTTPException(409,"Upload request mismatch")
                return {"id":prior["id"],"attachment":prior["media_id"],"created":prior["created"]}
        mime=file_mime(raw,declared)
        if kind=="photo" and mime not in ("image/jpeg","image/png","image/webp"): raise HTTPException(400,"Invalid photo")
        if kind in ("video","round") and mime!="video/mp4": raise HTTPException(400,"Invalid video")
        if kind=="voice" and mime not in ("audio/ogg","audio/mp4","audio/mpeg"): raise HTTPException(400,"Invalid voice")
        asset=store_media(c,n,name,mime,raw)
        now=int(time.time())
        mid=c.execute("INSERT INTO room_messages(room_id,sender,body,created) VALUES (?,?,?,?)",(rid,n,caption if kind!="file" else caption or "📎 "+name,now)).lastrowid
        c.execute("INSERT INTO room_message_media VALUES (?,?)",(mid,asset))
        c.execute("INSERT INTO attachment_details VALUES (?,?,?,?,?)",(asset,kind,duration,width,height))
        if request_id: c.execute("INSERT INTO room_attachment_orders VALUES (?,?,?,?)",(n,request_id,mid,signature))
        c.commit()
        return {"id":mid,"attachment":asset,"created":now}

@app.post("/v1/rooms/{rid}/attachments")
async def upload_room_attachment(rid:str,request:Request,name:str="file",mime:str="application/octet-stream",kind:str="file",duration:int=0,width:int=0,height:int=0,request_id:str="",caption:str=""):
    if kind not in ("file","voice","round","photo","video") or not 0<=duration<=3600 or not 0<=width<=4096 or not 0<=height<=4096 or len(caption)>1024 or (request_id and not re.fullmatch(r"-?[0-9]{1,20}",request_id)):raise HTTPException(400,"Invalid attachment metadata")
    _,n=await run_in_threadpool(session,request)
    if not await run_in_threadpool(allow,"upload:"+n): raise HTTPException(429,"Too many uploads")
    name=re.sub(r"[\x00-\x1f/\\]","_",name.strip())[:120] or "file"
    raw=await read_limited(request,MAX_MEDIA)
    return await run_in_threadpool(put_room_attachment,n,rid,name,mime,raw,kind,duration,width,height,request_id,caption)

@app.put("/v1/avatar")
async def upload_avatar(request:Request):
    _,n=await run_in_threadpool(session,request)
    if not await run_in_threadpool(allow,"avatar:"+n): raise HTTPException(429,"Too many uploads")
    return await run_in_threadpool(put_avatar,n,await read_limited(request,MAX_AVATAR))

@app.delete("/v1/avatar")
def remove_avatar(request:Request):
    _,n=session(request)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("DELETE FROM media WHERE id IN (SELECT media_id FROM avatars WHERE number=?)",(n,))
        c.execute("DELETE FROM avatars WHERE number=?",(n,))
        c.commit()
    return {"ok":True}

@app.get("/v1/media/{mid}")
def get_media(mid:str,request:Request):
    _,n=session(request)
    with db() as c:
        row=c.execute("""SELECT m.* FROM media m WHERE m.id=? AND
        (EXISTS(SELECT 1 FROM avatars a WHERE a.media_id=m.id) OR EXISTS(
         SELECT 1 FROM message_media a JOIN messages t ON t.id=a.message_id
         WHERE a.media_id=m.id AND (t.sender=? OR t.recipient=?)
         AND NOT EXISTS(SELECT 1 FROM hidden_messages h WHERE h.owner=? AND h.message_id=t.id)) OR EXISTS(
         SELECT 1 FROM room_message_media a JOIN room_messages r ON r.id=a.message_id
         JOIN room_members member ON member.room_id=r.room_id WHERE a.media_id=m.id AND member.number=?))""",(mid,n,n,n,n)).fetchone()
        if not row: raise HTTPException(404,"File not found")
        return Response(content=row["content"],media_type=row["mime"],headers={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff","Content-Disposition":"attachment"})

CATALOG={"heart":{"name":"Сердце","emoji":"💝","price":50},"bear":{"name":"Мишка","emoji":"🧸","price":100},"rose":{"name":"Роза","emoji":"🌹","price":75},"star":{"name":"Звезда","emoji":"🌟","price":150},"crystal":{"name":"Кристалл","emoji":"💎","price":250}}
CATALOG.update({"present":{"name":"Подарок","emoji":"🎁","price":100},"cake":{"name":"Торт","emoji":"🎂","price":120}})
GIFT_ART={"heart":"email_setup_heart","star":"star_reaction","crystal":"wallet_diamond_blue","present":"gift","cake":"cake"}
def memorial_animation(encoded):
    # Convert the bundled, quantized memorial illustration into vector-only Lottie.
    import zlib
    from collections import defaultdict
    if hashlib.sha256(encoded.encode()).hexdigest()!="e3c9d7956124b6262594afb62e380944ab4c05b8a98d5d9c322a74811657e92b":
        raise ValueError("Unexpected memorial image checksum")
    raw=zlib.decompress(base64.b64decode(encoded,validate=True))
    n,count=raw[:2]
    palette=raw[2:2+count*3]
    pixels=raw[2+count*3:]
    if (n,count)!=(96,24) or len(pixels)!=n*n or max(pixels)>=count:
        raise ValueError("Invalid memorial image")
    edges=[defaultdict(set) for _ in range(count)]
    for y in range(n):
        for x in range(n):
            color=pixels[y*n+x]
            e=edges[color]
            if y==0 or pixels[(y-1)*n+x]!=color: e[x,y].add((x+1,y))
            if x==n-1 or pixels[y*n+x+1]!=color: e[x+1,y].add((x+1,y+1))
            if y==n-1 or pixels[(y+1)*n+x]!=color: e[x+1,y+1].add((x,y+1))
            if x==0 or pixels[y*n+x-1]!=color: e[x,y+1].add((x,y))
    def prop(v): return {"a":0,"k":v}
    def transform(): return {"ty":"tr","p":prop([0,0]),"a":prop([0,0]),"s":prop([100,100]),"r":prop(0),"o":prop(100),"sk":prop(0),"sa":prop(0)}
    shapes=[]
    directions=[(1,0),(0,1),(-1,0),(0,-1)]
    for color,e in enumerate(edges):
        paths=[]
        while e:
            start=min(e)
            prev=start
            cur=min(e[start])
            e[start].remove(cur)
            if not e[start]: del e[start]
            vertices=[start]
            while cur!=start:
                vertices.append(cur)
                direction=directions.index((cur[0]-prev[0],cur[1]-prev[1]))
                options=e[cur]
                nxt=min(options,key=lambda p:(directions.index((p[0]-cur[0],p[1]-cur[1]))-direction-1)%4)
                options.remove(nxt)
                if not options: del e[cur]
                prev,cur=cur,nxt
            v=[]
            for j,b in enumerate(vertices):
                a=vertices[j-1]
                c=vertices[(j+1)%len(vertices)]
                if (b[0]-a[0],b[1]-a[1])!=(c[0]-b[0],c[1]-b[1]):
                    v.append([round(b[0]*512/n,3),round(b[1]*512/n,3)])
            if len(v)>=3:
                paths.append({"ty":"sh","ks":prop({"i":[[0,0]]*len(v),"o":[[0,0]]*len(v),"v":v,"c":True})})
        if paths:
            rgba=[v/255 for v in palette[color*3:color*3+3]]+[1]
            shapes.append({"ty":"gr","it":paths+[{"ty":"fl","c":prop(rgba),"o":prop(100),"r":2},transform()]})
    animation={"v":"5.7.4","fr":30,"ip":0,"op":30,"w":512,"h":512,"nm":"Bananchik memorial","ddd":0,"assets":[],"layers":[{"ddd":0,"ind":1,"ty":4,"nm":"Memorial artwork","sr":1,"ks":{"o":prop(100),"r":prop(0),"p":prop([0,0,0]),"a":prop([0,0,0]),"s":prop([100,100,100])},"ao":0,"shapes":shapes,"ip":0,"op":30,"st":0,"bm":0}]}
    data=gzip.compress(json.dumps(animation,separators=(",",":")).encode(),mtime=0)
    if len(data)>256*1024: raise ValueError("Memorial artwork exceeds TGS size limit")
    return data

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
    # Import bundled upstream animations once; never overwrite later admin edits.
    manifest=Path(__file__).with_name("original_gifts.json")
    if manifest.exists():
        c.execute("CREATE TABLE IF NOT EXISTS catalog_migrations (name TEXT PRIMARY KEY)")
        for kind, entry in json.loads(manifest.read_text()).items():
            migration="original-tgs-v1:"+kind
            if c.execute("SELECT 1 FROM catalog_migrations WHERE name=?",(migration,)).fetchone():
                continue
            if not c.execute("SELECT 1 FROM catalog_gifts WHERE kind=?",(kind,)).fetchone():
                spec=entry.get("catalog")
                if not spec: continue
                c.execute("INSERT INTO catalog_gifts(kind,name,emoji,price,supply,rarity,upgrade_enabled) VALUES (?,?,?,?,?,?,?)",
                          (kind,spec["name"],spec["emoji"],spec["price"],spec["supply"],spec["rarity"],0))
            data=base64.b64decode(entry["tgs"],validate=True)
            if len(data)>256*1024:
                raise ValueError("Oversized bundled gift")
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                raw=stream.read(4*1024*1024+1)
            if len(raw)>4*1024*1024:
                raise ValueError("Oversized bundled animation")
            animation=json.loads(raw)
            if not isinstance(animation,dict) or animation.get("w")!=512 or animation.get("h")!=512 or not isinstance(animation.get("layers"),list):
                raise ValueError("Invalid bundled animation")
            asset=hashlib.sha256(data).hexdigest()
            c.execute("INSERT OR IGNORE INTO gift_art VALUES (?,?)",(asset,data))
            c.execute("UPDATE catalog_gifts SET asset=? WHERE kind=?",(asset,kind))
            c.execute("INSERT INTO catalog_migrations VALUES (?)",(migration,))
    memorial=Path(__file__).with_name("bananchik_palette.b64")
    if memorial.is_file() and not c.execute("SELECT 1 FROM catalog_gifts WHERE kind='bananchik'").fetchone():
        data=memorial_animation(memorial.read_text().strip())
        asset=hashlib.sha256(data).hexdigest()
        c.execute("INSERT OR IGNORE INTO gift_art VALUES (?,?)",(asset,data))
        c.execute("INSERT OR IGNORE INTO catalog_gifts(kind,name,emoji,price,supply,rarity,upgrade_enabled,asset) VALUES (?,?,?,?,?,?,?,?)",("bananchik","Бананчик","🕯️",15,0,"common",0,asset))
    charger=Path(__file__).with_name("tecno_charger.json")
    if charger.is_file() and not c.execute("SELECT 1 FROM catalog_gifts WHERE kind='tecno-charger'").fetchone():
        data=gzip.compress(charger.read_bytes(),mtime=0)
        asset=hashlib.sha256(data).hexdigest()
        c.execute("INSERT OR IGNORE INTO gift_art VALUES (?,?)",(asset,data))
        c.execute("INSERT OR IGNORE INTO catalog_gifts(kind,name,emoji,price,supply,rarity,upgrade_enabled,asset) VALUES (?,?,?,?,?,?,?,?)",("tecno-charger","Зарядка TECNO","🔌",100,0,"common",0,asset))
    ai=Path(__file__).with_name("ai_hoshino.json")
    c.execute("CREATE TABLE IF NOT EXISTS catalog_migrations (name TEXT PRIMARY KEY)")
    if ai.is_file() and not c.execute("SELECT 1 FROM catalog_migrations WHERE name='ai-hoshino-art-v3'").fetchone():
        raw=ai.read_bytes()
        animation=json.loads(raw)
        if animation.get("w")!=512 or animation.get("h")!=512 or not animation.get("layers") or animation.get("assets"):
            raise ValueError("Invalid Ai Hoshino animation")
        data=gzip.compress(raw,mtime=0)
        if len(data)>64*1024: raise ValueError("Ai Hoshino TGS too large")
        asset=hashlib.sha256(data).hexdigest()
        c.execute("INSERT OR IGNORE INTO gift_art VALUES (?,?)",(asset,data))
        c.execute("INSERT OR IGNORE INTO catalog_gifts(kind,name,emoji,price,supply,rarity,upgrade_enabled,asset) VALUES (?,?,?,?,?,?,?,?)",("ai-hoshino","Ai Hoshino","💖",250,0,"rare",0,asset))
        c.execute("UPDATE catalog_gifts SET asset=? WHERE kind='ai-hoshino'",(asset,))
        c.execute("INSERT INTO catalog_migrations VALUES (?)",("ai-hoshino-art-v3",))
        c.execute("INSERT INTO admin_audit(action,kind,created) VALUES (?,?,?)",("artwork.redesign.v3","ai-hoshino",int(time.time())))
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
       COALESCE(v.title,'') AS verification_title, COALESCE(v.description,'') AS verification_description, COALESCE(v.symbol,0) AS verification_symbol, COALESCE(v.color,0) AS verification_color,
       (SELECT COUNT(*) FROM gifts g WHERE g.recipient=a.number) AS gift_count
FROM accounts a LEFT JOIN profiles p ON p.number=a.number
LEFT JOIN phone_aliases ph ON ph.number=a.number
LEFT JOIN profile_details pd ON pd.number=a.number
LEFT JOIN avatars av ON av.number=a.number
LEFT JOIN wallets w ON w.number=a.number
LEFT JOIN account_freezes f ON f.number=a.number
LEFT JOIN user_verifications v ON v.number=a.number
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

class AdminVerification(AdminAction):
    enabled:bool
    title:str=Field(default="",max_length=64)
    description:str=Field(default="",max_length=250)
    symbol:int=Field(default=0,ge=0,le=5)
    color:int=Field(default=0,ge=0,le=5)

@app.post("/v1/admin/users/{number}/verification")
def admin_verification(number:str,body:AdminVerification,request:Request):
    admin_auth(request)
    if not body.reason.strip() or (body.enabled and not body.title.strip()): raise HTTPException(400,"Specify verification title and reason")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        require_peer(c,number)
        sig,prev=admin_replay(c,number,"verification.set",body)
        if prev is not None: return prev
        if body.enabled:
            c.execute("INSERT OR REPLACE INTO user_verifications VALUES (?,?,?,?,?)",(number,body.title.strip(),body.description.strip(),body.symbol,body.color))
        else:
            c.execute("DELETE FROM user_verifications WHERE number=?",(number,))
        return admin_finish(c,number,"verification.set",body,sig,{"ok":True,"enabled":body.enabled,"title":body.title.strip(),"symbol":body.symbol,"color":body.color})

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

def gift_receipt(c,mid):
    row=c.execute("""SELECT g.kind,r.price AS paid_price,d.message,d.anonymous,d.visible,cg.*
        FROM gift_receipts r JOIN gifts g ON g.id=r.gift_id
        JOIN gift_details d ON d.gift_id=g.id JOIN catalog_gifts cg ON cg.kind=g.kind
        WHERE r.message_id=?""",(mid,)).fetchone()
    if not row: return None
    result=catalog_item(row)
    result["price"]=row["paid_price"]
    return result

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
        # Gift and its chat receipt commit together; retries return above.
        title=item["name"]
        note=body.message.strip()
        now=int(time.time())
        if n==peer:
            receipts=[(n,n,f"🎁 Вы приобрели подарок «{title}» за {item['price']} ⭐.")]
        elif body.anonymous:
            receipts=[(n,n,f"🎁 Вы отправили анонимный подарок «{title}»."),(peer,peer,f"🎁 Вы получили анонимный подарок «{title}».")]
        else:
            receipts=[(n,peer,f"🎁 Подарок «{title}»")]
        for sender,recipient,text in receipts:
            if note: text+="\n"+note
            mid=c.execute("INSERT INTO messages(sender,recipient,body,created) VALUES (?,?,?,?)",(sender,recipient,text,now)).lastrowid
            c.execute("INSERT INTO gift_receipts VALUES (?,?,?)",(mid,gid,item["price"]))
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


# Independent Toxicgram Bot API. Tokens are never stored in plaintext.
class BotCreate(BaseModel):
    name: str = Field(min_length=1,max_length=64)
    username: str = Field(min_length=5,max_length=32)

@app.post("/v1/bots")
def create_bot(body:BotCreate,request:Request):
    _,owner=session(request)
    if not allow("bot-create:"+owner,5): raise HTTPException(429,"Too many requests")
    username=body.username.strip().lstrip("@").lower()
    name=body.name.strip()
    if not name or not re.fullmatch(r"[a-z0-9_]{5,32}",username) or not username.endswith("bot"):
        raise HTTPException(400,"Username must end in bot")
    token=secrets.token_urlsafe(48)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT COUNT(*) FROM bots WHERE owner=?",(owner,)).fetchone()[0]>=20:
            raise HTTPException(429,"Bot limit")
        if c.execute("SELECT 1 FROM profile_details WHERE username=? COLLATE NOCASE",(username,)).fetchone():
            raise HTTPException(409,"Username taken")
        while True:
            d=f"{secrets.randbelow(100000000):08d}"
            n=f"TG-{d[:4]}-{d[4:]}"
            if not c.execute("SELECT 1 FROM accounts WHERE number=? UNION SELECT 1 FROM bots WHERE number=?",(n,n)).fetchone(): break
        c.execute("INSERT INTO bots(number,owner,token_hash) VALUES (?,?,?)",(n,owner,digest("bot:"+token)))
        c.execute("INSERT INTO profiles(number,name) VALUES (?,?)",(n,name))
        c.execute("INSERT INTO profile_details(number,username) VALUES (?,?)",(n,username))
        c.commit()
    return {"id":n,"username":username,"token":token}

@app.get("/v1/bots")
def list_bots(request:Request):
    _,owner=session(request)
    with db() as c:
        return {"bots":[dict(x) for x in c.execute("SELECT b.number AS id,b.active,p.name,d.username FROM bots b JOIN profiles p ON p.number=b.number JOIN profile_details d ON d.number=b.number WHERE b.owner=?",(owner,))]}

@app.post("/v1/bots/{number}/token")
def rotate_bot_token(number:str,request:Request):
    _,owner=session(request)
    token=secrets.token_urlsafe(48)
    with db() as c:
        if not c.execute("UPDATE bots SET token_hash=? WHERE number=? AND owner=? AND active=1",(digest("bot:"+token),number,owner)).rowcount:
            raise HTTPException(404,"Bot not found")
    return {"token":token}

def bot_identity(c,n):
    row=c.execute("SELECT p.name,d.username FROM profiles p LEFT JOIN profile_details d ON d.number=p.number WHERE p.number=?",(n,)).fetchone()
    return {"id":n,"is_bot":bool(c.execute("SELECT 1 FROM bots WHERE number=?",(n,)).fetchone()),"first_name":row["name"] if row else n,"username":row["username"] if row else None}

@app.api_route("/bot/{method}",methods=["GET","POST"])
async def bot_api(method:str,request:Request):
    from fastapi.responses import JSONResponse
    def fail(code,msg):
        return JSONResponse({"ok":False,"error_code":code,"description":msg},status_code=code)
    scheme,_,token=request.headers.get("Authorization","").partition(" ")
    if scheme.lower()!="bearer" or not re.fullmatch(r"[A-Za-z0-9_-]{64}",token):
        return fail(401,"Unauthorized")
    with db() as c:
        row=c.execute("SELECT number FROM bots WHERE token_hash=? AND active=1 AND NOT EXISTS(SELECT 1 FROM account_freezes WHERE number=bots.owner OR number=bots.number)",(digest("bot:"+token),)).fetchone()
    if not row: return fail(401,"Unauthorized")
    n=row["number"]
    if not allow("bot-api:"+n,120): return fail(429,"Too many requests")
    try:
        data=dict(request.query_params)
        if request.method=="POST":
            raw=await read_limited(request,65536)
            if raw:
                payload=json.loads(raw)
                if not isinstance(payload,dict): return fail(400,"Invalid JSON object")
                data.update(payload)
        with db() as c:
            if method=="getMe":
                result=bot_identity(c,n)
            elif method=="getUpdates":
                offset=max(0,int(data.get("offset",0)))
                limit=max(1,min(100,int(data.get("limit",100))))
                rows=c.execute("SELECT * FROM messages WHERE recipient=? AND id>=? ORDER BY id LIMIT ?",(n,offset,limit)).fetchall()
                result=[{"update_id":x["id"],"message":{"message_id":x["id"],"from":bot_identity(c,x["sender"]),"chat":{"id":x["sender"],"type":"private"},"date":x["created"],"text":x["body"]}} for x in rows]
            elif method in ("sendMessage","editMessageText","deleteMessage"):
                if request.method!="POST": return fail(405,"POST required")
                peer=normalize_number(str(data.get("chat_id","")))
                c.execute("BEGIN IMMEDIATE")
                require_peer(c,peer)
                if c.execute("SELECT 1 FROM blocks WHERE (owner=? AND peer=?) OR (owner=? AND peer=?)",(n,peer,peer,n)).fetchone():
                    return fail(403,"Messaging unavailable")
                if not c.execute("SELECT 1 FROM messages WHERE sender=? AND recipient=?",(peer,n)).fetchone():
                    return fail(403,"User must contact bot first")
                if method!="deleteMessage":
                    value=data.get("text")
                    if not isinstance(value,str) or not 1<=len(value.strip())<=4000: return fail(400,"Invalid text")
                    value=value.strip()
                if method=="sendMessage":
                    now=int(time.time())
                    mid=c.execute("INSERT INTO messages(sender,recipient,body,created) VALUES (?,?,?,?)",(n,peer,value,now)).lastrowid
                else:
                    mid=int(data.get("message_id",0))
                    old=c.execute("SELECT * FROM messages WHERE id=? AND sender=? AND recipient=?",(mid,n,peer)).fetchone()
                    if not old: return fail(404,"Message not found")
                    now=old["created"]
                    if method=="deleteMessage":
                        c.execute("DELETE FROM messages WHERE id=?",(mid,))
                    else:
                        c.execute("UPDATE messages SET body=? WHERE id=?",(value,mid))
                        c.execute("INSERT INTO message_edits VALUES (?,?) ON CONFLICT(message_id) DO UPDATE SET edited=excluded.edited",(mid,int(time.time())))
                result=True if method=="deleteMessage" else {"message_id":mid,"from":bot_identity(c,n),"chat":{"id":peer,"type":"private"},"date":now,"text":value}
                c.commit()
            else: return fail(404,"Unknown method")
        return {"ok":True,"result":result}
    except HTTPException as exc: return fail(exc.status_code,str(exc.detail))
    except (ValueError,TypeError,OverflowError): return fail(400,"Invalid parameters")
