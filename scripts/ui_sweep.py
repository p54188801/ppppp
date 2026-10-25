"""三角色全页面巡检：抓控制台错误 + 关键页截图。"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8905"
OUT = r"D:\EduFlow\docs\screenshots"

ROUTES = {
    "admin": ["/#/", "/#/courses", "/#/admin/users", "/#/admin/backups", "/#/search?q=%E6%95%B0%E6%8D%AE",
              "/#/notifications", "/#/profile", "/#/attendance"],
    "t1001": ["/#/", "/#/courses", "/#/courses/1", "/#/classes/1", "/#/classes/1/gradebook",
              "/#/attendance", "/#/search?q=%E6%95%B0%E6%8D%AE", "/#/profile"],
    "s2001": ["/#/", "/#/courses", "/#/my/assignments", "/#/assignments/1", "/#/grades",
              "/#/attendance", "/#/notifications", "/#/search?q=%E6%95%B0%E6%8D%AE", "/#/profile"],
}

errors: list[str] = []


def login(page, user):
    page.goto(f"{BASE}/#/login", wait_until="networkidle")
    page.fill('input[placeholder="请输入用户名"]', user)
    page.fill('input[placeholder="请输入密码"]', "Eduflow@2026")
    page.click('button[type="submit"]')
    page.wait_for_timeout(1800)


with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True)
    for user, routes in ROUTES.items():
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.on("console", lambda m: errors.append(f"[console] {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))
        login(page, user)
        for route in routes:
            page.goto(f"{BASE}{route}", wait_until="networkidle")
            page.wait_for_timeout(700)
            title = page.title()
            h1 = page.evaluate("() => (document.querySelector('h1')||{}).innerText || ''")
            print(f"{user:6} {route:38} -> {title} | {h1[:20]}")
        # 关键页截图
        if user == "admin":
            page.goto(f"{BASE}/#/admin/backups", wait_until="networkidle")
            page.wait_for_timeout(900)
            page.screenshot(path=f"{OUT}/18-backups.png")
            page.goto(f"{BASE}/#/search?q=%E6%95%B0%E6%8D%AE", wait_until="networkidle")
            page.wait_for_timeout(900)
            page.screenshot(path=f"{OUT}/19-search.png")
        if user == "t1001":
            page.goto(f"{BASE}/#/courses/1", wait_until="networkidle")
            page.wait_for_timeout(900)
            page.screenshot(path=f"{OUT}/20-announcements.png")
        ctx.close()
    browser.close()

print()
print("控制台错误:", len(errors))
for item in dict.fromkeys(errors):
    print("  -", item)
sys.exit(1 if errors else 0)
