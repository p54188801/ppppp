"""按钮巡检：逐页点击所有按钮，报告点了没反应/报错/接口失败的按钮。

用法：python scripts/ui_buttons.py [base_url]
"""

from __future__ import annotations

import sys
import urllib.parse

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"

PAGES = {
    "t1001": ["/#/", "/#/courses", "/#/courses/1", "/#/classes/1", "/#/classes/1/gradebook",
              "/#/attendance", "/#/search?q=%E6%95%B0%E6%8D%AE", "/#/profile", "/#/notifications"],
    "s2001": ["/#/", "/#/courses", "/#/my/assignments", "/#/assignments/1", "/#/grades",
              "/#/attendance", "/#/notifications", "/#/profile", "/#/search?q=1"],
    "admin": ["/#/", "/#/courses", "/#/admin/users", "/#/admin/backups", "/#/profile"],
}

# 这些按钮点了会改状态或退出，跳过
SKIP_TEXTS = ("退出", "删除", "移除", "恢复", "重置", "归档", "注销", "停止", "结束")

problems: list[str] = []
tested = 0


def login(page, user):
    page.goto(f"{BASE}/#/login", wait_until="networkidle")
    page.fill('input[placeholder="请输入用户名"]', user)
    page.fill('input[placeholder="请输入密码"]', "Eduflow@2026")
    page.click('button[type="submit"]')
    page.wait_for_timeout(1800)


with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True)
    for user, pages in PAGES.items():
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        login(page, user)

        for route in pages:
            page.goto(f"{BASE}{route}", wait_until="networkidle")
            page.wait_for_timeout(900)
            count = min(page.locator("button:visible").count(), 10)
            for i in range(count):
                # 每次点击前刷新，避免上一个弹窗挡住后面按钮
                page.reload(wait_until='networkidle')
                page.wait_for_timeout(500)
                btn = page.locator("button:visible").nth(i)
                try:
                    text = (btn.inner_text() or "").strip()[:20]
                except Exception:  # noqa: BLE001
                    continue
                if any(k in text for k in SKIP_TEXTS):
                    continue

                errors: list[str] = []
                fails: list[str] = []

                def on_console(msg, _e=errors):
                    if msg.type == "error":
                        _e.append(msg.text)

                def on_response(resp, _f=fails):
                    if resp.url.startswith(BASE) and resp.status >= 400 and "/api/" in resp.url:
                        _f.append(f"{resp.status} {urllib.parse.urlparse(resp.url).path}")

                page.on("console", on_console)
                page.on("response", on_response)
                try:
                    btn.click(timeout=4000, force=False)
                    page.wait_for_timeout(700)
                    tested += 1
                    if errors or fails:
                        problems.append(f"[{user}] {route} 「{text}」 -> {errors or fails}")
                except Exception as exc:  # noqa: BLE001
                    msg = str(exc).splitlines()[0][:100]
                    if "intercepts pointer events" in msg or "not visible" in msg:
                        continue
                    problems.append(f"[{user}] {route} 「{text}」 点击失败: {msg}")
                    tested += 1
                finally:
                    page.remove_listener("console", on_console)
                    page.remove_listener("response", on_response)
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(150)
                    # 回到该页（点击可能跳转）
                    if not page.url.endswith(route.split("?")[0]):
                        page.goto(f"{BASE}{route}", wait_until="networkidle")
                        page.wait_for_timeout(600)
        ctx.close()
    browser.close()

print(f"点击了 {tested} 个按钮，异常 {len(problems)} 个")
for p in problems:
    print("  ✗", p)
sys.exit(1 if problems else 0)
