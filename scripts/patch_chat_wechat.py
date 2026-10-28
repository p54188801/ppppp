"""群聊改造成微信样式：左右气泡 + 身份徽章 + 加载更早消息。"""

from pathlib import Path

# ---------------- 后端：支持 limit 参数 ----------------
r = Path(r"D:\EduFlow\backend\api\group_routes.py")
t = r.read_text(encoding="utf-8")
if "int_param(\"limit\")" not in t:
    t = t.replace(
        'return ok(group_service.group_detail(user, req.path_params["group_id"]))',
        'limit = req.int_param("limit", 100) or 100\n'
        '    return ok(group_service.group_detail(user, req.path_params["group_id"], limit=min(limit, 500)))',
    )
    r.write_text(t, encoding="utf-8")
    print("group_routes: 支持 limit")

# ---------------- 前端 ----------------
p = Path(r"D:\EduFlow\frontend\src\views\GroupView.vue")
t = p.read_text(encoding="utf-8")

if "loadMore" not in t:
    t = t.replace(
        "const sending = ref(false)",
        "const sending = ref(false)\nconst limit = ref(60)\nconst chatBox = ref(null)",
        1,
    )
    t = t.replace(
        "    current.value = await api.get(`/api/groups/${groupId.value}`)",
        "    current.value = await api.get(`/api/groups/${groupId.value}?limit=${limit.value}`)",
        1,
    )
    t = t.replace(
        "      current.value = await api.get(`/api/groups/${id}`)",
        "      current.value = await api.get(`/api/groups/${id}?limit=${limit.value}`)",
        1,
    )
    logic = '''
async function loadMore() {
  limit.value += 60
  await loadGroup()
}

function scrollToBottom() {
  const el = chatBox.value
  if (el) el.scrollTop = el.scrollHeight
}

function isMine(m) {
  return Number(m.sender_id) === Number(auth.user?.id)
}

function roleBadge(m) {
  if (m.sender_role === 'teacher' || m.sender_role === 'admin') {
    return { text: '老师', cls: 'teacher' }
  }
  return { text: '学生', cls: 'student' }
}
'''
    t = t.replace("async function send() {", logic + "\nasync function send() {", 1)

    # 消息列表替换成气泡
    start = t.find('<div class="chat-box">')
    end = t.find('</div>', t.find('<div v-if="!current.messages.length" class="empty">'))
    if start > 0 and end > 0:
        end = t.find("\n", end) + 1
        # 找到 chat-box 的闭合（在 chat-input 之前）
        chat_input = t.find('<div class="chat-input">', start)
        new_block = '''<div class="chat-box" ref="chatBox">
            <div v-if="current.messages.length >= limit" style="text-align: center; margin-bottom: 8px">
              <button class="btn sm" @click="loadMore">查看更早的消息</button>
            </div>
            <div
              v-for="m in current.messages"
              :key="m.id"
              class="msg-row"
              :class="{ mine: isMine(m) }"
            >
              <div class="msg-avatar" :class="roleBadge(m).cls">
                {{ (m.sender_name || '?').slice(0, 1) }}
              </div>
              <div class="msg-main">
                <div class="msg-head" :class="{ right: isMine(m) }">
                  <span class="msg-name">{{ m.sender_name }}</span>
                  <span class="role-pill" :class="roleBadge(m).cls">{{ roleBadge(m).text }}</span>
                  <span class="msg-time">{{ relativeTime(m.created_at) }}</span>
                </div>
                <div class="bubble" :class="{ mine: isMine(m) }">
                  <div v-if="m.content" class="bubble-text">{{ m.content }}</div>
                  <div v-if="m.kind === 'assignment'" class="bubble-assign">📋 {{ m.content }}</div>
                  <div v-if="m.file_name" class="bubble-file">
                    <span>{{ m.kind === 'image' ? '🖼' : '📎' }} {{ m.file_name }}</span>
                    <button class="btn sm" @click="downloadMessage(m)">下载</button>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="!current.messages.length" class="empty">还没有消息，打个招呼吧</div>
          </div>

          '''
        t = t[:start] + new_block + t[chat_input:]
        # 自动滚到底：在 send 后
        t = t.replace("    await loadGroup()\n  } catch (error) {\n    ui.error(error.message)\n  } finally {\n    sending.value = false\n  }", "    await loadGroup()\n    scrollToBottom()\n  } catch (error) {\n    ui.error(error.message)\n  } finally {\n    sending.value = false\n  }", 1)

    # 样式
    t = t.replace(".msg { padding: 8px 0; border-bottom: 1px dashed var(--border); }", "")
    t = t.replace(".msg.mine .msg-name { color: var(--primary); }", "")
    t = t.replace(".msg-head { display: flex; gap: 8px; align-items: baseline; }", "")
    t = t.replace(".msg-name { font-size: 13px; font-weight: 600; }", "")
    t = t.replace(".msg-body { margin-top: 4px; white-space: pre-wrap; word-break: break-word; }", "")
    t = t.replace(".msg-assign {\n  margin-top: 6px; padding: 8px 12px; border-radius: 10px;\n  background: rgba(255, 200, 87, 0.18); color: #8a5a00; font-size: 13px;\n}", "")
    t = t.replace(".msg-file { margin-top: 6px; display: flex; gap: 10px; align-items: center; font-size: 13px; }", "")

    extra_css = '''
/* 微信式气泡 */
.chat-box { max-height: 52vh; overflow-y: auto; padding: 4px 6px 4px 2px; }
.msg-row { display: flex; gap: 10px; margin-bottom: 16px; align-items: flex-start; }
.msg-row.mine { flex-direction: row-reverse; }
.msg-avatar {
  width: 34px; height: 34px; border-radius: 10px; flex-shrink: 0;
  display: grid; place-items: center; font-size: 14px; font-weight: 650; color: #fff;
}
.msg-avatar.teacher { background: linear-gradient(135deg, #ffc857, #ff9f43); }
.msg-avatar.student { background: linear-gradient(135deg, #6fb6ff, #3e8ef7); }
.msg-main { max-width: 72%; min-width: 0; }
.msg-head { display: flex; gap: 6px; align-items: center; margin-bottom: 4px; }
.msg-head.right { justify-content: flex-end; }
.msg-name { font-size: 12.5px; color: var(--text-dim); }
.msg-time { font-size: 11px; color: var(--text-faint); }
.role-pill {
  font-size: 10.5px; padding: 1px 7px; border-radius: 999px; font-weight: 600;
}
.role-pill.teacher { background: #fff3d6; color: #a86a00; border: 1px solid #ffd88a; }
.role-pill.student { background: #e3f0ff; color: #1a6fc4; border: 1px solid #b6d8ff; }
.bubble {
  background: #fff; border: 1px solid var(--border); border-radius: 12px;
  padding: 9px 12px; box-shadow: 0 2px 8px rgba(63, 110, 180, 0.06);
  display: inline-block; max-width: 100%; text-align: left;
}
.msg-row.mine .bubble {
  background: linear-gradient(135deg, #ffb347, #ff8a3d);
  border-color: transparent; color: #fff;
}
.msg-row.mine .bubble .bubble-text { color: #fff; }
.bubble-text { white-space: pre-wrap; word-break: break-word; font-size: 14px; line-height: 1.55; }
.bubble-assign {
  margin-top: 4px; padding: 6px 10px; border-radius: 8px;
  background: rgba(255, 200, 87, 0.22); color: #8a5a00; font-size: 13px;
}
.msg-row.mine .bubble-assign { background: rgba(255,255,255,.25); color: #fff; }
.bubble-file { display: flex; gap: 10px; align-items: center; font-size: 13px; margin-top: 4px; }
'''
    t = t.replace("</style>", extra_css + "\n</style>", 1)

    p.write_text(t, encoding="utf-8")
    print("GroupView: 已改成微信式气泡")
