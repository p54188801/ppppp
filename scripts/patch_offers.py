"""课程页顶部加「为你推荐」卡片：按班级匹配课程，可接受/拒绝。"""

from pathlib import Path

p = Path(r"D:\EduFlow\frontend\src\views\CourseListView.vue")
t = p.read_text(encoding="utf-8")

if "offers" not in t:
    # script：状态 + 加载 + 响应
    t = t.replace(
        "const actingId = ref(0)",
        "const actingId = ref(0)\nconst offers = ref([])",
        1,
    )
    logic = '''
async function loadOffers() {
  if (!auth.isStudent) return
  try {
    offers.value = await api.get('/api/my/course-offers')
  } catch {
    offers.value = []
  }
}

async function respondOffer(offer, accept) {
  try {
    await api.post(`/api/course-offers/${offer.offer_id}/${accept ? 'accept' : 'reject'}`)
    ui.success(accept ? `已加入《${offer.name}》` : '已忽略该推荐')
    offers.value = offers.value.filter((o) => o.offer_id !== offer.offer_id)
    if (accept) await load()
  } catch (error) {
    ui.error(error.message)
  }
}
'''
    t = t.replace("async function load(", logic + "\nasync function load(", 1)

    # 挂载时加载推荐
    t = t.replace(
        "onMounted(load)",
        "onMounted(async () => {\n  await load()\n  await loadOffers()\n})",
        1,
    )

    # 模板：插在 page-head 之后
    card = '''
    <div v-if="auth.isStudent && offers.length" class="card" style="margin-bottom: 16px">
      <div class="card-title">
        <span>为你推荐 · {{ offers.length }} 门</span>
        <span class="faint small">按你的班级匹配，可接受或拒绝</span>
      </div>
      <div
        v-for="offer in offers"
        :key="offer.offer_id"
        class="row between"
        style="padding: 10px 0; border-bottom: 1px solid var(--border)"
      >
        <div>
          <strong>{{ offer.name }}</strong>
          <div class="faint small">
            {{ offer.code }} · {{ offer.teacher_name }} · {{ offer.credits }} 学分
          </div>
        </div>
        <div class="row" style="gap: 8px">
          <button class="btn sm" @click="respondOffer(offer, false)">拒绝</button>
          <button class="btn sm primary" @click="respondOffer(offer, true)">接受</button>
        </div>
      </div>
    </div>
'''
    idx = t.find("<template>")
    head_end = t.find("</div>", t.find('<div class="page-head">'))
    # 在 page-head 的结束处（第一个 </div> 之后另找闭合）——改用简单锚点：紧跟 page-head 块后的换行
    marker = "    </div>\n\n"
    pos = t.find(marker, idx)
    if pos > 0:
        t = t[: pos + len(marker)] + card + t[pos + len(marker):]
    else:
        t = t.replace("<template>", "<template>" + card, 1)

    p.write_text(t, encoding="utf-8")
    print("CourseListView: 已加入课程推荐卡片")
else:
    print("CourseListView: 已存在推荐卡片")
