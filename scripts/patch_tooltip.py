"""全局悬停提示：鼠标停在按钮/链接上 2 秒显示说明，移开消失。"""

from pathlib import Path

p = Path(r"D:\EduFlow\frontend\src\App.vue")
t = p.read_text(encoding="utf-8")

if "hoverTip" not in t:
    # 1) 状态与逻辑
    logic = '''
// ---------------------------------------------------------------------------
// 悬停 2 秒显示功能说明
// ---------------------------------------------------------------------------
const hoverTip = ref({ show: false, text: '', x: 0, y: 0 })
let hoverTimer = null

const TIP_TEXT = {
  登录: '输入账号密码进入系统',
  注册: '新用户登记，学生和老师都能注册',
  立即注册: '第一次使用请先注册账号',
}

function tipLabel(el) {
  const explicit = el.getAttribute('data-tip')
  if (explicit) return explicit
  const text = (el.innerText || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ')
  if (!text) return ''
  if (text.length > 18) return ''
  return TIP_TEXT[text] || `点击「${text}」`
}

function onHoverIn(event) {
  const el = event.target.closest && event.target.closest('button, a, .nav-item')
  if (!el) return
  const label = tipLabel(el)
  if (!label) return
  const rect = el.getBoundingClientRect()
  clearTimeout(hoverTimer)
  hoverTimer = setTimeout(() => {
    hoverTip.value = {
      show: true,
      text: label,
      x: Math.min(rect.left, window.innerWidth - 260),
      y: rect.bottom + 8,
    }
  }, 2000)
}

function onHoverOut() {
  clearTimeout(hoverTimer)
  hoverTip.value.show = false
}
'''
    t = t.replace("onMounted(() => {", logic + "\nonMounted(() => {", 1)

    # 2) 注册监听
    t = t.replace(
        "  window.addEventListener('keydown', onKeydown)",
        "  window.addEventListener('keydown', onKeydown)\n"
        "  window.addEventListener('mouseover', onHoverIn)\n"
        "  window.addEventListener('mouseout', onHoverOut)",
        1,
    )
    t = t.replace(
        "  window.removeEventListener('keydown', onKeydown)",
        "  window.removeEventListener('keydown', onKeydown)\n"
        "  window.removeEventListener('mouseover', onHoverIn)\n"
        "  window.removeEventListener('mouseout', onHoverOut)",
        1,
    )

    # 3) 模板里加浮层
    t = t.replace(
        "  <!-- 全局提示 -->",
        """  <!-- 悬停说明 -->
  <div
    v-if="hoverTip.show"
    class="hover-tip"
    :style="{ left: hoverTip.x + 'px', top: hoverTip.y + 'px' }"
  >
    {{ hoverTip.text }}
  </div>

  <!-- 全局提示 -->""",
        1,
    )

    p.write_text(t, encoding="utf-8")
    print("App.vue: 已加入悬停说明")

# 4) 样式
css = Path(r"D:\EduFlow\frontend\src\styles\main.css")
c = css.read_text(encoding="utf-8")
if "hover-tip" not in c:
    c += """

/* 悬停 2 秒出现的功能说明 */
.hover-tip {
  position: fixed;
  z-index: 400;
  max-width: 240px;
  padding: 8px 12px;
  font-size: 12.5px;
  line-height: 1.5;
  color: #1d3557;
  background: #fff;
  border: 1px solid #dbe8f6;
  border-radius: 10px;
  box-shadow: 0 10px 24px rgba(63, 110, 180, 0.18);
  pointer-events: none;
  animation: tip-in 0.15s ease-out;
}
@keyframes tip-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
"""
    css.write_text(c, encoding="utf-8")
    print("main.css: 已加入 hover-tip 样式")
