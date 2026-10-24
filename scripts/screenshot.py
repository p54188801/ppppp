"""视觉验收脚本：用系统 Edge 逐页截图。

前提：后端已经在 127.0.0.1:8765 运行（python -m backend.cli serve）。
用法：python scripts/screenshot.py
产物：docs/screenshots/*.png，以及控制台错误汇总。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
BASE = "http://127.0.0.1:8765"
OUT.mkdir(parents=True, exist_ok=True)

CONSOLE_ERRORS: list[str] = []
PAGES: list[str] = []


def shoot(page, name: str) -> None:
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)
    PAGES.append(name)
    print(f"  [shot] {name}")


def login(page, username: str, password: str = "Eduflow@2026") -> None:
    page.goto(f"{BASE}/#/login", wait_until="networkidle")
    page.fill('input[placeholder="请输入用户名"]', username)
    page.fill('input[placeholder="请输入密码"]', password)
    page.click('button[type="submit"]')
    page.wait_for_timeout(1500)


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.on("console", lambda msg: CONSOLE_ERRORS.append(f"{msg.type}: {msg.text}")
                if msg.type == "error" else None)
        page.on("pageerror", lambda err: CONSOLE_ERRORS.append(f"pageerror: {err}"))

        # ---------------- 匿名：登录页 ----------------
        page.goto(f"{BASE}/#/login", wait_until="networkidle")
        shoot(page, "01-login")

        # ---------------- 管理员 ----------------
        if target in ("all", "admin"):
            print("[admin]")
            login(page, "admin")
            page.wait_for_timeout(1200)
            shoot(page, "02-admin-dashboard")
            page.goto(f"{BASE}/#/admin/users", wait_until="networkidle")
            page.wait_for_timeout(800)
            shoot(page, "03-admin-users")

        # ---------------- 教师 ----------------
        if target in ("all", "teacher"):
            print("[teacher]")
            page.evaluate("localStorage.clear()")
            login(page, "t1001")
            page.wait_for_timeout(1200)
            shoot(page, "04-teacher-dashboard")
            page.goto(f"{BASE}/#/courses", wait_until="networkidle")
            page.wait_for_timeout(800)
            shoot(page, "05-teacher-courses")
            # 打开第一门课
            card = page.locator(".card").first
            if card.count():
                card.click()
                page.wait_for_timeout(1200)
                shoot(page, "06-course-detail")
            # 教学班详情（种子数据里 id=1 的教学班）
            page.goto(f"{BASE}/#/classes/1", wait_until="networkidle")
            page.wait_for_timeout(1200)
            shoot(page, "07-class-detail")
            # 成绩册：从教学班页跳转
            page.goto(f"{BASE}/#/classes/1/gradebook", wait_until="networkidle")
            page.wait_for_timeout(1200)
            shoot(page, "08-gradebook")
            page.goto(f"{BASE}/#/attendance", wait_until="networkidle")
            page.wait_for_timeout(800)
            shoot(page, "09-attendance-teacher")

        # ---------------- 学生 ----------------
        if target in ("all", "student"):
            print("[student]")
            page.evaluate("localStorage.clear()")
            login(page, "s2001")
            page.wait_for_timeout(1200)
            shoot(page, "10-student-dashboard")
            page.goto(f"{BASE}/#/my/assignments", wait_until="networkidle")
            page.wait_for_timeout(800)
            shoot(page, "11-my-assignments")
            # 作业详情
            rows = page.locator("tbody tr, .card")
            if rows.count():
                page.goto(f"{BASE}/#/assignments/1", wait_until="networkidle")
                page.wait_for_timeout(1000)
                shoot(page, "11b-assignment-detail")
            page.goto(f"{BASE}/#/grades", wait_until="networkidle")
            page.wait_for_timeout(800)
            shoot(page, "12-transcript")
            page.goto(f"{BASE}/#/attendance", wait_until="networkidle")
            page.wait_for_timeout(800)
            shoot(page, "13-attendance-student")
            page.goto(f"{BASE}/#/notifications", wait_until="networkidle")
            page.wait_for_timeout(800)
            shoot(page, "14-notifications")

        browser.close()

    print(f"\n共截图 {len(PAGES)} 张 -> {OUT}")
    if CONSOLE_ERRORS:
        print("\n控制台错误：")
        for line in dict.fromkeys(CONSOLE_ERRORS):
            print(f"  - {line}")
        return 1
    print("控制台无错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
