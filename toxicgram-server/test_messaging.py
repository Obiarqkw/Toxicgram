import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
import server

class MessagingTest(unittest.TestCase):
    def test_private_messages_and_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            server.DB = str(Path(temp) / "test.sqlite3")
            server.PEPPER = "test-only-key-not-for-deployment-0000000"
            server.TOKEN = ""
            with TestClient(server.app) as client:
                def account(tid):
                    n,code=server.issue(tid)
                    res=client.post("/v1/auth/verify",json={"number":n,"code":code})
                    self.assertEqual(res.status_code,200)
                    return n,{"Authorization":"Bearer "+res.json()["access_token"]}
                a,ha=account(1); b,hb=account(2); c,hc=account(3)
                self.assertEqual(client.get("/v1/chats").status_code,401)
                sent=client.post("/v1/messages",headers=ha,json={"recipient":b,"text":"hello"})
                self.assertEqual(sent.status_code,200); mid=sent.json()["id"]
                self.assertEqual(client.get("/v1/chats",headers=hb).json()["chats"][0]["unread"],1)
                self.assertEqual(client.get("/v1/chats/"+a+"/messages",headers=hc).json()["messages"],[])
                self.assertEqual(client.put(f"/v1/messages/{mid}",headers=hc,json={"text":"bad"}).status_code,404)
                self.assertEqual(client.put(f"/v1/messages/{mid}",headers=hb,json={"text":"bad"}).status_code,403)
                self.assertEqual(client.put(f"/v1/messages/{mid}",headers=ha,json={"text":"edited"}).status_code,200)
                history=client.get("/v1/chats/"+a+"/messages",headers=hb).json()["messages"]
                self.assertEqual(history[0]["text"],"edited");self.assertGreater(history[0]["edited"],0)
                self.assertEqual(client.put("/v1/chats/"+a+"/read",headers=hb,json={"last_id":mid}).status_code,200)
                self.assertEqual(client.get("/v1/chats",headers=hb).json()["chats"][0]["unread"],0)
                self.assertEqual(client.put("/v1/chats/"+a+"/settings",headers=hb,json={"pinned":True,"archived":True}).status_code,200)
                self.assertEqual(client.get("/v1/chats",headers=hb).json()["chats"][0]["archived"],1)
                self.assertEqual(client.get("/v1/chats",headers=ha).json()["chats"][0]["archived"],0)
                self.assertEqual(client.delete(f"/v1/messages/{mid}?everyone=true",headers=hb).status_code,403)
                self.assertEqual(client.delete(f"/v1/messages/{mid}",headers=hb).status_code,200)
                self.assertEqual(client.get("/v1/chats/"+a+"/messages",headers=hb).json()["messages"],[])
                self.assertEqual(len(client.get("/v1/chats/"+b+"/messages",headers=ha).json()["messages"]),1)
                self.assertEqual(client.delete(f"/v1/messages/{mid}?everyone=true",headers=ha).status_code,200)
                self.assertEqual(client.get("/v1/chats/"+b+"/messages",headers=ha).json()["messages"],[])
                self.assertEqual(client.post("/v1/messages",headers=ha,json={"recipient":a,"text":"note"}).status_code,200)
                self.assertEqual(client.get("/v1/chats",headers=ha).json()["chats"][0]["unread"],0)

    def test_phone_profiles_rooms_and_reactions(self):
        with tempfile.TemporaryDirectory() as temp:
            server.DB=str(Path(temp)/"test.sqlite3");server.PEPPER="test-only-key-not-for-deployment-0000000";server.TOKEN=""
            with TestClient(server.app) as client:
                def register(tid,prefix):
                    n,code=server.issue(tid)
                    phone=server.phone_for(n,prefix)
                    result=client.post("/v1/auth/verify",json={"number":phone,"code":code})
                    self.assertEqual(result.status_code,200)
                    self.assertEqual(result.json()["number"],n)
                    self.assertEqual(result.json()["phone"],phone)
                    return n,phone,{"Authorization":"Bearer "+result.json()["access_token"]}
                a,pa,ha=register(11,"+7");b,pb,hb=register(12,"+1");c,pc,hc=register(13,"+388")
                self.assertTrue(pa.startswith("+7000"));self.assertTrue(pb.startswith("+1000"));self.assertTrue(pc.startswith("+388000"))
                self.assertEqual(client.put("/v1/profile",headers=ha,json={"name":"Alice","username":"alice_test","bio":"Hello"}).status_code,200)
                self.assertEqual(client.get("/v1/users/@alice_test",headers=hb).json()["number"],a)
                self.assertEqual(client.put("/v1/profile",headers=hb,json={"name":"Bob","username":"ALICE_TEST"}).status_code,409)
                new=server.phone_for(a,"+388")
                self.assertNotEqual(pa,new)
                self.assertEqual(client.get("/v1/users/"+pa,headers=hb).status_code,404)
                self.assertEqual(client.get("/v1/users/"+new,headers=hb).json()["number"],a)
                mid=client.post("/v1/messages",headers=ha,json={"recipient":pb,"text":"hello"}).json()["id"]
                self.assertEqual(client.put(f"/v1/messages/{mid}/reaction",headers=hc,json={"emoji":"👍"}).status_code,404)
                self.assertEqual(client.put(f"/v1/messages/{mid}/reaction",headers=hb,json={"emoji":"👍"}).status_code,200)
                self.assertEqual(client.get("/v1/chats/"+b+"/messages",headers=ha).json()["messages"][0]["reactions"][0]["count"],1)
                self.assertEqual(client.put("/v1/users/"+a+"/block",headers=hb,json={"blocked":True}).status_code,200)
                self.assertEqual(client.post("/v1/messages",headers=ha,json={"recipient":b,"text":"blocked"}).status_code,403)
                self.assertEqual(client.put("/v1/users/"+a+"/block",headers=hb,json={"blocked":False}).status_code,200)
                for kind in ("group","channel"):
                    rid=client.post("/v1/rooms",headers=ha,json={"kind":kind,"title":"Test "+kind}).json()["id"]
                    self.assertEqual(client.get(f"/v1/rooms/{rid}/messages",headers=hc).status_code,404)
                    self.assertEqual(client.post(f"/v1/rooms/{rid}/invite",headers=ha,json={"number":pb}).status_code,200)
                    self.assertEqual(client.post(f"/v1/rooms/{rid}/invite",headers=hb,json={"number":pc}).status_code,403)
                    self.assertEqual(client.post(f"/v1/rooms/{rid}/messages",headers=ha,json={"text":"owner post"}).status_code,200)
                    self.assertEqual(client.post(f"/v1/rooms/{rid}/messages",headers=hb,json={"text":"member post"}).status_code,200 if kind=="group" else 403)
                    self.assertEqual(client.get(f"/v1/rooms/{rid}/messages",headers=hb).status_code,200)
                    sync=client.get("/v1/rooms/sync",headers=hb).json()
                    self.assertIn(rid,{room["id"] for room in sync["rooms"]})
                    self.assertIn("owner post",[m["text"] for m in sync["messages"] if m["room_id"]==rid])
                    self.assertEqual(client.get("/v1/rooms/sync?after="+str(sync["cursor"]),headers=hb).json()["messages"],[])
                    self.assertNotIn(rid,{room["id"] for room in client.get("/v1/rooms/sync",headers=hc).json()["rooms"]})
                    self.assertEqual(client.delete(f"/v1/rooms/{rid}/membership",headers=hb).status_code,200)
                    self.assertEqual(client.get(f"/v1/rooms/{rid}/messages",headers=hb).status_code,404)
                    self.assertNotIn(rid,{m["room_id"] for m in client.get("/v1/rooms/sync",headers=hb).json()["messages"]})


    def test_attachments_gifts_stories(self):
        with tempfile.TemporaryDirectory() as temp:
            server.DB=str(Path(temp)/"test.sqlite3");server.PEPPER="test-only-key-not-for-deployment-0000000";server.TOKEN=""
            with TestClient(server.app) as client:
                def register(tid):
                    n,code=server.issue(tid)
                    res=client.post("/v1/auth/verify",json={"number":n,"code":code})
                    return n,{"Authorization":"Bearer "+res.json()["access_token"]}
                a,ha=register(21);b,hb=register(22);c,hc=register(23)
                raw=b"hello attachment"
                res=client.post("/v1/attachments",params={"recipient":b,"name":"note.txt"},headers=ha,content=raw)
                self.assertEqual(res.status_code,200);mid=res.json()["id"];aid=res.json()["attachment"]
                self.assertEqual(client.get("/v1/media/"+aid,headers=hb).content,raw)
                self.assertEqual(client.get("/v1/media/"+aid,headers=hc).status_code,404)
                self.assertEqual(client.get("/v1/media/"+aid).status_code,401)
                self.assertEqual(client.get("/v1/chats/"+a+"/messages",headers=hb).json()["messages"][0]["attachment"]["id"],aid)
                self.assertEqual(client.delete(f"/v1/messages/{mid}",headers=hb).status_code,200)
                self.assertEqual(client.get("/v1/media/"+aid,headers=hb).status_code,404)
                self.assertEqual(client.get("/v1/media/"+aid,headers=ha).status_code,200)
                self.assertEqual(client.delete(f"/v1/messages/{mid}?everyone=true",headers=ha).status_code,200)
                self.assertEqual(client.get("/v1/media/"+aid,headers=ha).status_code,404)
                self.assertEqual(client.put("/v1/avatar",headers=ha,content=raw).status_code,400)
                self.assertEqual(client.get("/v1/gifts",headers=ha).json()["balance"],1000)
                res=client.post("/v1/gifts",headers=ha,json={"recipient":b,"kind":"heart"})
                self.assertEqual(res.status_code,200)
                self.assertEqual(client.get("/v1/gifts",headers=ha).json()["balance"],950)
                self.assertEqual(client.get("/v1/gifts",headers=hb).json()["received"][0]["serial"],res.json()["serial"])
                order={"recipient":b,"kind":"cake","request_id":"test-order-1","anonymous":True,"message":"Hello"}
                first=client.post("/v1/gifts",headers=ha,json=order)
                second=client.post("/v1/gifts",headers=ha,json=order)
                self.assertEqual(first.status_code,200)
                self.assertEqual(first.json(),second.json())
                self.assertEqual(client.get("/v1/gifts",headers=ha).json()["balance"],830)
                chat=client.get("/v1/chats/"+a+"/messages",headers=hb).json()["messages"]
                self.assertEqual(len(chat),1)
                self.assertIn("🎁",chat[0]["text"])
                anonymous=client.get("/v1/chats/"+b+"/messages",headers=hb).json()["messages"]
                self.assertEqual(len(anonymous),1)
                self.assertIn("анонимный",anonymous[0]["text"])
                self.assertIn("Hello",anonymous[0]["text"])
                self_order={"recipient":a,"kind":"heart","request_id":"self-purchase"}
                self.assertEqual(client.post("/v1/gifts",headers=ha,json=self_order).status_code,200)
                self.assertEqual(client.post("/v1/gifts",headers=ha,json=self_order).status_code,200)
                receipts=client.get("/v1/chats/"+a+"/messages",headers=ha).json()["messages"]
                self.assertEqual(sum("приобрели" in m["text"] for m in receipts),1)

                own=client.get("/v1/users/"+b+"/gifts",headers=hb).json()["received"]
                self.assertEqual(len(own),2)
                self.assertNotIn("sender",own[0])
                gid=own[0]["id"]
                self.assertEqual(client.get("/v1/users/"+b+"/gifts",headers=hc).json()["received"],[])
                self.assertEqual(client.put(f"/v1/gifts/{gid}/visibility",headers=hc,json={"visible":True}).status_code,404)
                self.assertEqual(client.put(f"/v1/gifts/{gid}/visibility",headers=hb,json={"visible":True}).status_code,200)
                public=client.get("/v1/users/"+b+"/gifts",headers=hc).json()["received"]
                self.assertEqual(len(public),1)
                self.assertNotIn("sender",public[0])
                self.assertEqual(public[0]["serial"],first.json()["serial"])
                client.post("/v1/messages",headers=ha,json={"recipient":b,"text":"hi"})
                sid=client.post("/v1/stories",headers=ha,json={"text":"story"}).json()["id"]
                self.assertEqual(len(client.get("/v1/stories",headers=hb).json()["stories"]),1)
                self.assertEqual(client.get("/v1/stories",headers=hc).json()["stories"],[])
                self.assertEqual(client.delete(f"/v1/stories/{sid}",headers=hb).status_code,404)
                self.assertEqual(client.delete(f"/v1/stories/{sid}",headers=ha).status_code,200)
                self.assertEqual(client.get("/v1/stories",headers=hb).json()["stories"],[])

    def test_admin_catalog_and_limited_gift(self):
        with tempfile.TemporaryDirectory() as temp:
            server.DB=str(Path(temp)/"test.sqlite3")
            server.PEPPER="test-only-key-not-for-deployment-0000000"
            server.TOKEN=""
            previous=server.ADMIN_KEY
            server.ADMIN_KEY="test-admin-key-not-for-deployment-000000000"
            admin={"Authorization":"Bearer "+server.ADMIN_KEY}
            try:
                with TestClient(server.app) as client:
                    self.assertEqual(client.get("/admin").status_code,200)
                    self.assertEqual(client.get("/v1/admin/catalog").status_code,401)
                    n,code=server.issue(91)
                    h={"Authorization":"Bearer "+client.post("/v1/auth/verify",json={"number":n,"code":code}).json()["access_token"]}
                    self.assertEqual(client.get("/v1/admin/catalog",headers=h).status_code,401)
                    data=client.get("/v1/admin/catalog",headers=admin).json()
                    memorial=next(g for g in data["catalog"] if g["kind"]=="bananchik")
                    self.assertEqual((memorial["name"],memorial["price"],memorial["active"]),("Бананчик",15,1))
                    self.assertEqual(client.get("/v1/gift-art/"+memorial["asset"]).status_code,200)
                    pepe=next(g for g in data["catalog"] if g["kind"]=="plush-pepe")
                    self.assertEqual((pepe["price"],pepe["supply"],pepe["rarity"],pepe["upgrade_enabled"],pepe["active"]),(500,1000,"legendary",1,1))
                    self.assertEqual(client.get("/v1/gift-art/"+pepe["asset"]).status_code,200)
                    import gzip,json
                    charger=next(g for g in data["catalog"] if g["kind"]=="tecno-charger")
                    self.assertEqual((charger["name"],charger["price"],charger["active"]),("Зарядка TECNO",100,1))
                    charger_response=client.get("/v1/gift-art/"+charger["asset"])
                    self.assertEqual(charger_response.status_code,200)
                    self.assertLess(len(charger_response.content),64*1024)
                    charger_art=json.loads(gzip.decompress(charger_response.content))
                    self.assertEqual((charger_art["w"],charger_art["h"],charger_art["fr"],charger_art["op"]),(512,512,30,90))
                    self.assertTrue(any(layer["ks"]["p"]["a"]==1 for layer in charger_art["layers"]))
                    art=json.loads(gzip.decompress(client.get("/v1/gift-art/"+pepe["asset"]).content))
                    self.assertTrue(art["layers"])
                    self.assertEqual((art["w"],art["h"]),(512,512))
                    import base64,hashlib
                    manifest=json.loads(server.Path(server.__file__).with_name("original_gifts.json").read_text())
                    for kind,entry in manifest.items():
                        item=next(g for g in data["catalog"] if g["kind"]==kind)
                        self.assertEqual(item["asset"],hashlib.sha256(base64.b64decode(entry["tgs"])).hexdigest())
                        if "catalog" in entry:
                            for field in ("name","price","supply","rarity"):
                                self.assertEqual(item[field],entry["catalog"][field])
                            self.assertEqual(item["remaining"],item["supply"])

                    with server.db() as db:
                        db.execute("DELETE FROM catalog_migrations WHERE name='original-tgs-v1:plush-pepe'")
                        db.execute("UPDATE catalog_gifts SET asset='',price=501,issued=3 WHERE kind='plush-pepe'")
                        server.seed_catalog(db)
                        after=db.execute("SELECT asset,price,issued FROM catalog_gifts WHERE kind='plush-pepe'").fetchone()
                        self.assertEqual(tuple(after),(pepe["asset"],501,3))
                        db.execute("UPDATE catalog_gifts SET asset='',price=500,issued=0 WHERE kind='plush-pepe'")
                        server.seed_catalog(db)
                        self.assertEqual(db.execute("SELECT asset FROM catalog_gifts WHERE kind='plush-pepe'").fetchone()[0],"")
                        db.execute("UPDATE catalog_gifts SET asset=? WHERE kind='plush-pepe'",(pepe["asset"],))
                    self.assertEqual(client.post("/v1/admin/art",headers=h,content=b"{}").status_code,401)
                    self.assertEqual(client.post("/v1/admin/art",headers=admin,content=b"{}").status_code,400)
                    self.assertNotIn("plush-pepe",[g["kind"] for g in client.get("/v1/gifts",headers=h).json()["catalog"]])
                    self.assertIn("plush-pepe",[g["kind"] for g in client.get("/v1/gifts?dynamic=true",headers=h).json()["catalog"]])
                    edit={k:pepe[k] for k in ("kind","name","emoji","price","rarity","asset")}
                    edit.update(supply=1,upgrade_enabled=True,active=True)
                    self.assertEqual(client.put("/v1/admin/catalog",headers=h,json=edit).status_code,401)
                    self.assertEqual(client.put("/v1/admin/catalog",headers=admin,json=edit).status_code,200)
                    order={"recipient":n,"kind":"plush-pepe","request_id":"one","expected_price":499}
                    self.assertEqual(client.post("/v1/gifts",headers=h,json=order).status_code,412)
                    order["expected_price"]=500
                    first=client.post("/v1/gifts",headers=h,json=order)
                    self.assertEqual(first.status_code,200)
                    self.assertEqual(client.post("/v1/gifts",headers=h,json=order).json(),first.json())
                    order["request_id"]="two"
                    self.assertEqual(client.post("/v1/gifts",headers=h,json=order).status_code,410)
                    self.assertEqual(client.get("/v1/gifts",headers=h).json()["balance"],500)
                    self.assertEqual(client.get("/v1/users/"+n+"/gifts",headers=h).json()["received"][0]["num"],1)
            finally:
                server.ADMIN_KEY=previous


    def test_admin_user_management(self):
        with tempfile.TemporaryDirectory() as temp:
            server.DB=str(Path(temp)/"test.sqlite3")
            server.PEPPER="test-only-key-not-for-deployment-0000000"
            server.TOKEN=""
            previous=server.ADMIN_KEY
            server.ADMIN_KEY="test-admin-key-not-for-deployment-000000000"
            admin={"Authorization":"Bearer "+server.ADMIN_KEY}
            try:
                with TestClient(server.app) as client:
                    n,code=server.issue(121)
                    login=client.post("/v1/auth/verify",json={"number":n,"code":code})
                    h={"Authorization":"Bearer "+login.json()["access_token"]}
                    path="/v1/admin/users/"+n
                    self.assertEqual(client.get(path,headers=h).status_code,401)
                    self.assertEqual(client.get("/v1/admin/users",headers=h).status_code,401)
                    self.assertEqual(client.put("/v1/profile",headers=h,json={"name":"Test User","username":"admin_test_user","bio":"Test bio"}).status_code,200)
                    listing=client.get("/v1/admin/users?q=admin_test_user",headers=admin).json()["users"]
                    self.assertEqual(len(listing),1)
                    self.assertEqual(listing[0]["number"],n)
                    self.assertNotIn("telegram_id",listing[0])
                    self.assertNotIn("code_hash",listing[0])
                    self.assertEqual(client.get(path,headers=admin).json()["user"]["balance"],1000)
                    body={"request_id":"a"*32,"delta":500,"reason":"test credit"}
                    self.assertEqual(client.post(path+"/stars",headers=h,json=body).status_code,401)
                    self.assertEqual(client.post(path+"/stars",headers=admin,json=body).json()["balance"],1500)
                    self.assertEqual(client.post(path+"/stars",headers=admin,json=body).json()["balance"],1500)
                    self.assertEqual(client.post(path+"/stars",headers=admin,json={**body,"delta":1}).status_code,409)
                    self.assertEqual(client.post(path+"/stars",headers=admin,json={**body,"request_id":"b"*32,"delta":-2000}).status_code,409)
                    self.assertEqual(client.post(path+"/stars",headers=admin,json={**body,"request_id":"c"*32,"delta":-200}).json()["balance"],1300)
                    grant={"request_id":"d"*32,"kind":"plush-pepe","reason":"test grant"}
                    self.assertEqual(client.post(path+"/gift",headers=h,json=grant).status_code,401)
                    first=client.post(path+"/gift",headers=admin,json=grant)
                    self.assertEqual(first.status_code,200)
                    self.assertEqual(client.post(path+"/gift",headers=admin,json=grant).json(),first.json())
                    self.assertEqual(client.get("/v1/gifts",headers=h).json()["balance"],1300)
                    received=client.get("/v1/users/"+n+"/gifts",headers=h).json()["received"]
                    self.assertEqual(len(received),1);self.assertNotIn("sender",received[0])
                    self.assertEqual(received[0]["num"],1)
                    with server.db() as db:
                        db.execute("UPDATE catalog_gifts SET supply=1 WHERE kind='plush-pepe'")
                        db.execute("UPDATE accounts SET issued=0 WHERE number=?",(n,))
                    self.assertEqual(client.post(path+"/gift",headers=admin,json={**grant,"request_id":"e"*32}).status_code,410)
                    _,fresh=server.issue(121)
                    freeze={"request_id":"f"*32,"reason":"test freeze","frozen":True}
                    self.assertEqual(client.post(path+"/freeze",headers=h,json=freeze).status_code,401)
                    self.assertEqual(client.post(path+"/freeze",headers=admin,json=freeze).status_code,200)
                    self.assertEqual(client.get("/v1/me",headers=h).status_code,401)
                    self.assertEqual(client.post("/v1/auth/verify",json={"number":n,"code":fresh}).status_code,401)
                    self.assertIsNone(server.issue(121))
                    self.assertEqual(client.get(path,headers=admin).json()["user"]["frozen"],1)
                    self.assertEqual(client.post(path+"/freeze",headers=admin,json={**freeze,"request_id":"1"*32,"frozen":False}).status_code,200)
                    self.assertEqual(client.get("/v1/me",headers=h).status_code,401)
                    _,newcode=server.issue(121)
                    self.assertEqual(client.post("/v1/auth/verify",json={"number":n,"code":newcode}).status_code,200)
                    profile=client.get(path,headers=admin).json()
                    self.assertEqual(profile["user"]["balance"],1300)
                    self.assertEqual(profile["user"]["frozen"],0)
                    self.assertEqual(len(profile["gifts"]),1)
                    self.assertEqual(len(profile["audit"]),5)
            finally:
                server.ADMIN_KEY=previous


    def test_original_client_profiles_and_rooms(self):
        with tempfile.TemporaryDirectory() as temp:
            server.DB=str(Path(temp)/"test.sqlite3")
            server.PEPPER="test-only-key-not-for-deployment-0000000"
            server.TOKEN=""
            with TestClient(server.app) as client:
                def login(tid):
                    n,code=server.issue(tid)
                    res=client.post("/v1/auth/verify",json={"number":n,"code":code})
                    return n,{"Authorization":"Bearer "+res.json()["access_token"]}
                a,ha=login(161);b,hb=login(162);c,hc=login(163)
                path="/v1/profile/partial"
                result=client.put(path,headers=ha,json={"first_name":"Alex","last_name":"Tester","bio":"Bio text","username":"alex_toxic"})
                self.assertEqual(result.status_code,200)
                self.assertEqual(result.json()["name"],"Alex Tester")
                self.assertEqual(client.put(path,headers=ha,json={"bio":"New bio"}).json()["last_name"],"Tester")
                self.assertFalse(client.get("/v1/username/check?username=alex_toxic",headers=hb).json()["available"])
                self.assertEqual(client.put(path,headers=hb,json={"username":"alex_toxic"}).status_code,409)
                self.assertEqual(client.get("/v1/users-search?q=alex_toxic",headers=hb).json()["users"][0]["number"],a)
                self.assertEqual(client.get("/v1/me",headers=ha).json()["bio"],"New bio")
                room=client.post("/v1/rooms",headers=ha,json={"title":"Private group","kind":"group","members":[b]}).json()
                numeric=room["numeric_id"]
                details=client.get("/v1/rooms/by-id/"+str(numeric),headers=hb).json()
                self.assertEqual(len(details["users"]),2)
                self.assertEqual(client.get("/v1/rooms/by-id/"+str(numeric),headers=hc).status_code,404)
                self.assertEqual(client.get("/v1/rooms",headers=hb).json()["rooms"][0]["numeric_id"],numeric)
                msg=client.post("/v1/rooms/"+room["id"]+"/messages",headers=hb,json={"text":"hello group"}).json()
                self.assertGreater(msg["created"],0)
                self.assertEqual(client.get("/v1/rooms/"+room["id"]+"/messages",headers=ha).json()["messages"][0]["text"],"hello group")
                channel=client.post("/v1/rooms",headers=ha,json={"title":"Private channel","kind":"channel","about":"Channel description","members":[b]}).json()
                self.assertEqual(channel["mode"],"channel")
                self.assertEqual(channel["about"],"Channel description")
                self.assertEqual(client.post("/v1/rooms/"+channel["id"]+"/messages",headers=hb,json={"text":"not allowed"}).status_code,403)
                self.assertEqual(client.post("/v1/rooms/"+channel["id"]+"/messages",headers=ha,json={"text":"channel post"}).status_code,200)
                server.init()
                self.assertEqual(client.get("/v1/rooms/by-id/"+str(numeric),headers=hb).json()["room"]["id"],room["id"])


    def test_incoming_sync_and_presence(self):
        with tempfile.TemporaryDirectory() as temp:
            server.DB=str(Path(temp)/"test.sqlite3")
            server.PEPPER="test-only-key-not-for-deployment-0000000"
            server.TOKEN=""
            with TestClient(server.app) as client:
                def login(tid):
                    n,code=server.issue(tid)
                    r=client.post("/v1/auth/verify",json={"number":n,"code":code})
                    return n,{"Authorization":"Bearer "+r.json()["access_token"]}
                a,ha=login(181);b,hb=login(182);c,hc=login(183)
                self.assertEqual(client.get("/v1/sync").status_code,401)
                self.assertEqual(client.get("/v1/sync",headers=hb).json()["messages"],[])
                first=client.post("/v1/messages",headers=ha,json={"recipient":b,"text":"hello"}).json()["id"]
                initial=client.get("/v1/sync",headers=hb).json()
                self.assertEqual([m["id"] for m in initial["messages"]],[first])
                self.assertEqual(initial["users"][0]["number"],a)
                self.assertEqual(client.get("/v1/sync",headers=hc).json()["messages"],[])
                self.assertEqual(client.get("/v1/sync",headers=hc).json()["statuses"],[])
                self.assertGreater(client.get("/v1/users/"+b,headers=ha).json()["online_until"],initial["server_time"])
                self.assertEqual(client.get("/v1/users/"+b,headers=hc).json()["last_seen"],0)
                self.assertEqual(client.put("/v1/chats/"+a+"/read",headers=hb,json={"last_id":first}).status_code,200)
                receipt=client.get("/v1/sync",headers=ha).json()
                self.assertEqual(receipt["statuses"][0]["read_outbox"],first)
                self.assertEqual(client.get("/v1/sync",headers=hb).json()["messages"],[])
                second=client.post("/v1/messages",headers=ha,json={"recipient":b,"text":"second"}).json()["id"]
                update=client.get("/v1/sync?after="+str(initial["cursor"]),headers=hb).json()
                self.assertEqual([m["id"] for m in update["messages"]],[second])
                self.assertEqual(client.get("/v1/sync?after="+str(update["cursor"]),headers=hb).json()["messages"],[])
                self.assertEqual(client.put("/v1/users/"+a+"/block",headers=hb,json={"blocked":True}).status_code,200)
                self.assertEqual(client.get("/v1/users/"+b,headers=ha).json()["last_seen"],0)


    def test_referral_rewards_only_after_first_successful_login(self):
        with tempfile.TemporaryDirectory() as temp:
            server.DB=str(Path(temp)/"test.sqlite3")
            server.PEPPER="test-only-key-not-for-deployment-0000000"
            server.TOKEN=""
            with TestClient(server.app) as client:
                def verify(n,code):
                    return client.post("/v1/auth/verify",json={"number":n,"code":code})
                inviter,code=server.issue(201)
                first=verify(inviter,code)
                self.assertEqual(first.status_code,200)
                h={"Authorization":"Bearer "+first.json()["access_token"]}
                stats=server.referral_stats(201)
                ref=stats["code"]
                self.assertEqual(server.referral_stats(201)["code"],ref)
                self.assertEqual(stats["balance"],1000)
                self.assertIsNone(server.referral_stats(999))
                other,_=server.issue(202)
                other_ref=server.referral_stats(202)["code"]
                invited,invite_code=server.issue(203,ref)
                stats=server.referral_stats(201)
                self.assertEqual((stats["pending"],stats["completed"],stats["earned"],stats["balance"]),(1,0,0,1000))
                wrong="000000" if invite_code!="000000" else "111111"
                self.assertEqual(verify(invited,wrong).status_code,401)
                self.assertEqual(server.referral_stats(201)["balance"],1000)
                # Reopening with another referral cannot change attribution.
                with server.db() as db:
                    db.execute("UPDATE accounts SET issued=0 WHERE number=?",(invited,))
                _,invite_code=server.issue(203,other_ref)
                self.assertEqual(server.referral_stats(202)["total"],0)
                self.assertEqual(verify(invited,invite_code).status_code,200)
                stats=server.referral_stats(201)
                self.assertEqual((stats["pending"],stats["completed"],stats["earned"],stats["balance"]),(0,1,500,1500))
                self.assertEqual(client.get("/v1/gifts",headers=h).json()["balance"],1500)
                self.assertEqual(verify(invited,invite_code).status_code,401)
                # Self-referral, returning users and virtual-number changes cannot pay again.
                with server.db() as db:
                    db.execute("UPDATE accounts SET issued=0 WHERE number IN (?,?,?)",(invited,inviter,other))
                _,next_code=server.issue(203,ref)
                phone=server.phone_for(invited,"+7")
                self.assertEqual(verify(phone,next_code).status_code,200)
                _,self_code=server.issue(201,ref)
                self.assertEqual(verify(inviter,self_code).status_code,200)
                _,other_code=server.issue(202,ref)
                self.assertEqual(verify(other,other_code).status_code,200)
                self.assertEqual(server.referral_stats(201)["earned"],500)
                second,second_code=server.issue(204,ref)
                self.assertEqual(verify(second,second_code).status_code,200)
                server.init()
                self.assertEqual(server.referral_stats(201)["completed"],2)
                self.assertEqual(client.get("/v1/gifts",headers=h).json()["balance"],2000)
                with server.db() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM admin_user_actions WHERE number=? AND action='referral.reward'",(inviter,)).fetchone()[0],2)
                invalid,invalid_code=server.issue(205,"invalid")
                self.assertEqual(verify(invalid,invalid_code).status_code,200)
                self.assertEqual(server.referral_stats(201)["completed"],2)


    def test_voice_video_avatar_and_gift_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            server.DB=str(Path(temp)/"test.sqlite3")
            server.PEPPER="test-only-key-not-for-deployment-0000000"
            server.TOKEN=""
            with TestClient(server.app) as client:
                def login(tid):
                    n,code=server.issue(tid)
                    r=client.post("/v1/auth/verify",json={"number":n,"code":code})
                    return n,{"Authorization":"Bearer "+r.json()["access_token"]}
                a,ha=login(221);b,hb=login(222);c,hc=login(223)
                sent=client.post("/v1/gifts",headers=ha,json={"recipient":b,"kind":"heart"})
                self.assertEqual(sent.status_code,200)
                self.assertEqual(client.get("/v1/me",headers=hb).json()["gift_count"],1)
                self.assertEqual(client.get("/v1/users/"+b,headers=ha).json()["gift_count"],0)
                gid=client.get("/v1/users/"+b+"/gifts",headers=hb).json()["received"][0]["id"]
                self.assertEqual(client.put(f"/v1/gifts/{gid}/visibility",headers=hb,json={"visible":True}).status_code,200)
                self.assertEqual(client.get("/v1/users/"+b,headers=ha).json()["gift_count"],1)
                import base64
                # PNG fixture, avatar permissions, replacement and removal.
                png=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aKp0AAAAASUVORK5CYII=")
                avatar=client.put("/v1/avatar",headers=ha,content=png)
                self.assertEqual(avatar.status_code,200)
                aid=avatar.json()["avatar"]
                self.assertEqual(client.get("/v1/users/"+a,headers=hb).json()["avatar"],aid)
                self.assertEqual(client.get("/v1/media/"+aid,headers=hb).content,png)
                self.assertEqual(client.get("/v1/media/"+aid).status_code,401)
                self.assertEqual(client.delete("/v1/avatar",headers=ha).status_code,200)
                self.assertEqual(client.get("/v1/media/"+aid,headers=hb).status_code,404)
                # Container signatures are validated; full decoder playback is a device test.
                voice=b"OggS"+bytes(80)
                params={"recipient":b,"name":"voice.ogg","mime":"audio/ogg","kind":"voice","duration":3,"request_id":"123"}
                result=client.post("/v1/attachments",headers=ha,params=params,content=voice)
                self.assertEqual(result.status_code,200)
                self.assertEqual(client.post("/v1/attachments",headers=ha,params=params,content=voice).json(),result.json())
                msg=result.json()
                self.assertEqual(client.get("/v1/media/"+msg["attachment"],headers=hb).content,voice)
                self.assertEqual(client.get("/v1/media/"+msg["attachment"],headers=hc).status_code,404)
                sync=client.get("/v1/sync",headers=hb).json()
                self.assertEqual(len(sync["messages"]),2)
                self.assertIn("🎁",sync["messages"][0]["text"])
                self.assertEqual(sync["messages"][1]["attachment"]["kind"],"voice")
                self.assertEqual(sync["messages"][1]["attachment"]["duration"],3)
                self.assertEqual(client.post("/v1/attachments",headers=ha,params={**params,"request_id":"124"},content=b"invalid").status_code,400)
                video=bytes([0,0,0,24])+b"ftypmp42"+bytes(80)
                v=client.post("/v1/attachments",headers=ha,params={"recipient":b,"name":"video.mp4","mime":"video/mp4","kind":"round","duration":5,"width":360,"height":360,"request_id":"125"},content=video)
                self.assertEqual(v.status_code,200)
                msgs=client.get("/v1/chats/"+a+"/messages",headers=hb).json()["messages"]
                self.assertEqual(msgs[-1]["attachment"]["kind"],"round")
                self.assertEqual(msgs[-1]["attachment"]["width"],360)


if __name__=="__main__":
    unittest.main()
