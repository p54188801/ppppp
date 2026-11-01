"""让桌面窗口使用「晨光教务」自己的图标，而不是 Python 图标。"""

from pathlib import Path

p = Path(r"D:\EduFlow\run.py")
t = p.read_text(encoding="utf-8")

if "_apply_window_icon" not in t:
    helper = '''

# ---------------------------------------------------------------------------
# 窗口图标：pywebview 默认用 python.exe 的图标，这里手动换成自己的 .ico
# ---------------------------------------------------------------------------
APP_USER_MODEL_ID = "Chenguang.EduFlow.Desktop"
ICON_PATH = Path(__file__).resolve().parent / "assets" / "logo.ico"


def _set_app_user_model_id() -> None:
    """让任务栏把本程序当成独立应用（图标、分组都独立）。"""
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:  # noqa: BLE001
        pass


def _apply_window_icon(title: str) -> None:
    """找到窗口句柄并设置大/小图标。"""
    try:
        import ctypes
        import time as _time

        if not ICON_PATH.exists():
            return
        user32 = ctypes.windll.user32
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        LR_DEFAULTSIZE = 0x00000040
        WM_SETICON = 0x0080
        ICON_SMALL, ICON_BIG = 0, 1

        hwnd = 0
        for _ in range(40):  # 最多等 8 秒
            hwnd = user32.FindWindowW(None, title)
            if hwnd:
                break
            _time.sleep(0.2)
        if not hwnd:
            return

        big = user32.LoadImageW(None, str(ICON_PATH), IMAGE_ICON, 0, 0,
                                LR_LOADFROMFILE | LR_DEFAULTSIZE)
        small = user32.LoadImageW(None, str(ICON_PATH), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        if big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)
        if small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small)
        logger.info("已设置窗口图标：%s", ICON_PATH.name)
    except Exception:  # noqa: BLE001
        logger.debug("设置窗口图标失败", exc_info=True)


'''
    t = t.replace("def main(", helper + "\ndef main(", 1)
    # 启动时设置 AppUserModelID
    t = t.replace("def main(", '''def main(''', 1)
    t = t.replace("    args = parser.parse_args(argv)", "    args = parser.parse_args(argv)\n    _set_app_user_model_id()", 1)
    # 窗口创建后异步设置图标
    t = t.replace(
        "    threading.Thread(target=_watchdog, name=\"window-watchdog\", daemon=True).start()",
        "    threading.Thread(target=_watchdog, name=\"window-watchdog\", daemon=True).start()\n"
        "    threading.Thread(target=_apply_window_icon, args=(WINDOW_TITLE,), name=\"window-icon\", daemon=True).start()",
        1,
    )
    p.write_text(t, encoding="utf-8")
    print("run.py: 已加入窗口图标设置")
else:
    print("run.py: 已存在")
