import sqlite3
import http.client
import json

DB = r"D:\EduFlow\data\eduflow.db"
conn = sqlite3.connect(DB)
print("user_version:", conn.execute("PRAGMA user_version").fetchone()[0])
print("before:", conn.execute("SELECT must_change_password FROM users WHERE username='admin'").fetchone())
conn.execute("UPDATE users SET must_change_password=1 WHERE username='admin'")
conn.commit()
print("after :", conn.execute("SELECT must_change_password FROM users WHERE username='admin'").fetchone())
conn.close()


def call(method, path, body=None, token=None):
    c = http.client.HTTPConnection("127.0.0.1", 8765, timeout=15)
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    c.request(method, path, body=json.dumps(body).encode() if body else None, headers=h)
    r = c.getresponse()
    d = r.read()
    c.close()
    return r.status, d


st, b = call("POST", "/api/auth/login", {"username": "admin", "password": "Eduflow@2026"})
data = json.loads(b)["data"]
tok = data["token"]
print("login must_change:", data["user"]["must_change_password"])
print("GET /api/users      ->", call("GET", "/api/users", token=tok)[0], "(期望 403)")
print("GET /api/auth/me    ->", call("GET", "/api/auth/me", token=tok)[0], "(期望 200)")

# 注册 + 用邀请码入班
st, b = call("POST", "/api/auth/register", {"username": "stu3001", "password": "abc123456",
                                            "real_name": "李小明", "number": "S3001"})
print("注册无邀请码 ->", st)
