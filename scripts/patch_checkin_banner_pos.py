"""把签到横幅提到标签页上方，任何标签都能看到。"""

from pathlib import Path

p = Path(r"D:\EduFlow\frontend\src\views\GroupView.vue")
t = p.read_text(encoding="utf-8")

start_marker = "          <!-- 进行中的签到 -->"
end_marker = '\n          <div ref="chatBox" class="chat-box">'

s = t.find(start_marker)
e = t.find(end_marker, s)
if s > 0 and e > s:
    banner = t[s:e]
    t = t[:s] + t[e + 1:]  # 去掉横幅（保留 chat-box 行）
    # 插到 tabs 之后
    tabs_end = t.find("</div>", t.find('<div class="tabs">')) + len("</div>")
    t = t[:tabs_end] + "\n" + banner + t[tabs_end:]
    p.write_text(t, encoding="utf-8")
    print("GroupView: 签到横幅已提到标签页上方")
else:
    print("未找到横幅位置", s, e)
