"""手机端巡检：390x844 视口下登录教师/学生，检查横向溢出并截图。

用法：python scripts/mobile_sweep.py [port]
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8905
BASE = f"http://127.0.0.1:{PORT}"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"

errors: list[str] = []
problems: list[str] = []


def login(page, user: str) -> None:
    page.goto(f"{BASE}/#/login", wait_until="networkidle")
    page.fill('input[placeholder="请输入用户名"]', user)
    page.fill('input[placeholder="请输入密码"]', "Eduflow@2026")
    page.click('button[type="submit"]')
    page.wait_for_timeout(3200)


def check_width(page, label: str) -> None:
    size = page.evaluate(
        "() => ({scroll: document.documentElement.scrollWidth, inner: window.innerWidth})"
    )
    print(f"  {label}: scrollWidth={size['scroll']} innerWidth={size['inner']}")
    if size["scroll"] > size["inner"] + 1:
        problems.append(f"{label} 横向溢出 {size['scroll']} > {size['inner']}")


with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True)
    for user, role in (("t1001", "teacher"), ("s2001", "student")):
        ctx = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
        )
        page = ctx.new_page()
        page.on(
            "console",
            lambda m: errors.append(f"[console] {m.text}") if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))

        login(page, user)
        check_width(page, f"{role} 工作台")
        if role == "teacher":
            page.screenshot(path=str(OUT / "26-mobile-dashboard.png"))
            page.locator(".mobile-menu").click()
            page.wait_for_timeout(400)
            page.screenshot(path=str(OUT / "27-mobile-menu.png"))
            page.locator(".sidebar-close").click()
            page.wait_for_timeout(300)
        else:
            page.screenshot(path=str(OUT / "29-mobile-student.png"))

        page.goto(f"{BASE}/#/courses/1", wait_until="networkidle")
        page.wait_for_timeout(800)
        check_width(page, f"{role} 课程详情")
        if role == "teacher":
            page.screenshot(path=str(OUT / "28-mobile-chapters.png"))
        ctx.close()
    browser.close()

print()
print("控制台错误:", len(errors))
for item in dict.fromkeys(errors):
    print("  -", item)
print("布局问题:", len(problems))
for item in problems:
    print("  -", item)

sys.exit(1 if errors or problems else 0)
