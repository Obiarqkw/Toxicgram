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
if __name__=="__main__":
    unittest.main()
