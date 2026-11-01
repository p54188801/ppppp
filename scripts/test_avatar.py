import base64
import http.client
import json

BASE = ("127.0.0.1", 8765)


def login(user, pwd):
    c = http.client.HTTPConnection(*BASE, timeout=15)
    c.request("POST", "/api/auth/login", body=json.dumps({"username": user, "password": pwd}),
              headers={"Content-Type": "application/json"})
    r = c.getresponse()
    data = json.loads(r.read())
    c.close()
    return data["data"]["token"]


def upload(token, ctype="image/png", filename="a.png", payload=None):
    bnd = "----boundary7MA4YWxkTrZu0gW"
    png = payload or base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    head = (
        "--" + bnd + "\r\n"
        'Content-Disposition: form-data; name="file"; filename="' + filename + '"\r\n'
        "Content-Type: " + ctype + "\r\n\r\n"
    ).encode()
    body = head + png + ("\r\n--" + bnd + "--\r\n").encode()
    c = http.client.HTTPConnection(*BASE, timeout=20)
    c.request("POST", "/api/auth/avatar", body=body,
              headers={"Content-Type": "multipart/form-data; boundary=" + bnd,
                       "Authorization": "Bearer " + token})
    r = c.getresponse()
    raw = r.read()
    c.close()
    return r.status, raw


token = login("群学生76061", "abc123456")
st, raw = upload(token)
print("上传状态:", st)
if st == 200:
    d = json.loads(raw)["data"]
    print("头像 data URL 长度:", len(d["avatar"]))
    c = http.client.HTTPConnection(*BASE, timeout=15)
    c.request("GET", "/api/auth/me", headers={"Authorization": "Bearer " + token})
    me = json.loads(c.getresponse().read())["data"]
    print("me 带头像:", me.get("avatar", "")[:30])
else:
    print("失败:", raw.decode()[:200])

# 非图片应被拒绝
st2, raw2 = upload(token, ctype="text/plain", filename="a.txt", payload=b"hello")
print("上传 txt:", st2, raw2.decode()[:80])
