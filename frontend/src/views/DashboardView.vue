<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, deadlineText, formatDate, relativeTime } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const ui = useUiStore()
const router = useRouter()

const loading = ref(true)
const data = ref(null)
const pending = ref([])
const openSessions = ref([])
const notices = ref([])

const trendMax = computed(() => {
  const trend = data.value?.trend || []
  return Math.max(1, ...trend.map((item) => Math.max(item.submissions, item.logins)))
})

async function load() {
  loading.value = true
  try {
    data.value = await api.get('/api/dashboard')
    if (auth.isStudent) {
      pending.value = await api.get('/api/my/assignments', { status: 'pending' })
      openSessions.value = await api.get('/api/my/attendance/open')
      const inbox = await api.get('/api/notifications', { page_size: 3 })
      notices.value = inbox.items || []
    }
  } catch (error) {
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 6) return '夜深了'
  if (hour < 11) return '早上好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
})

function openClass(id) {
  router.push({ name: 'class-detail', params: { id } })
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>{{ greeting }}，{{ auth.displayName }}</h1>
        <p>
          {{ auth.roleLabel }} · 今天是
          {{ new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }) }}
        </p>
      </div>
      <button class="btn" :disabled="loading" @click="load">{{ loading ? '刷新中…' : '刷新数据' }}</button>
    </div>

    <div v-if="loading" class="loading">正在加载…</div>

    <!-- ================= 管理员 ================= -->
    <template v-else-if="auth.isAdmin && data">
      <div class="grid cols-4">
        <div class="stat">
          <div class="stat-label">学生总数</div>
          <div class="stat-value">{{ data.users.student }}</div>
          <div class="stat-hint">在籍学生账号</div>
        </div>
        <div class="stat">
          <div class="stat-label">教师总数</div>
          <div class="stat-value">{{ data.users.teacher }}</div>
          <div class="stat-hint">授课教师</div>
        </div>
        <div class="stat">
          <div class="stat-label">课程 / 教学班</div>
          <div class="stat-value">{{ data.courses }} / {{ data.classes }}</div>
          <div class="stat-hint">本学期开设</div>
        </div>
        <div class="stat">
          <div class="stat-label">出勤率</div>
          <div class="stat-value">{{ data.attendance_rate }}%</div>
          <div class="stat-hint">全部签到记录</div>
        </div>
      </div>

      <div class="grid cols-2" style="margin-top: 16px">
        <div class="card">
          <div class="card-title">
            <span>近 7 天活跃度</span>
            <span class="faint small">提交 / 登录</span>
          </div>
          <div
            v-for="item in data.trend"
            :key="item.date"
            class="row"
            style="gap: 10px; margin-bottom: 8px"
          >
            <div class="small faint mono" style="width: 74px">{{ item.date.slice(5) }}</div>
            <div style="flex: 1">
              <div class="progress" style="margin-bottom: 4px">
                <i :style="{ width: `${(item.submissions / trendMax) * 100}%` }" />
              </div>
              <div class="progress">
                <i
                  :style="{
                    width: `${(item.logins / trendMax) * 100}%`,
                    background: 'var(--purple)',
                  }"
                />
              </div>
            </div>
            <div class="small muted mono" style="width: 64px; text-align: right">
              {{ item.submissions }} / {{ item.logins }}
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-title"><span>最近操作</span></div>
          <div
            v-for="log in data.recent_logs.slice(0, 8)"
            :key="log.id"
            class="row between"
            style="padding: 6px 0; border-bottom: 1px solid var(--border)"
          >
            <div>
              <div class="small">{{ log.detail || log.action }}</div>
              <div class="faint small">{{ log.username || 'system' }} · {{ log.entity }}</div>
            </div>
            <div class="faint small">{{ relativeTime(log.created_at) }}</div>
          </div>
          <div v-if="!data.recent_logs.length" class="empty">暂无记录</div>
        </div>
      </div>

      <div class="grid cols-3" style="margin-top: 16px">
        <div class="stat">
          <div class="stat-label">作业总数</div>
          <div class="stat-value">{{ data.assignments }}</div>
        </div>
        <div class="stat">
          <div class="stat-label">提交总数</div>
          <div class="stat-value">{{ data.submissions }}</div>
        </div>
        <div class="stat">
          <div class="stat-label">管理账号</div>
          <div class="stat-value">{{ data.users.admin }}</div>
        </div>
      </div>
    </template>

    <!-- ================= 教师 ================= -->
    <template v-else-if="auth.isTeacher && data">
      <div class="grid cols-4">
        <div class="stat">
          <div class="stat-label">我的教学班</div>
          <div class="stat-value">{{ data.totals.classes }}</div>
        </div>
        <div class="stat">
          <div class="stat-label">学生人数</div>
          <div class="stat-value">{{ data.totals.students }}</div>
        </div>
        <div class="stat">
          <div class="stat-label">待批改</div>
          <div class="stat-value" :style="{ color: data.totals.ungraded ? 'var(--warning)' : '' }">
            {{ data.totals.ungraded }}
          </div>
          <div class="stat-hint">未评分的提交</div>
        </div>
        <div class="stat">
          <div class="stat-label">即将截止</div>
          <div class="stat-value">{{ (data.upcoming || []).length }}</div>
          <div class="stat-hint">按截止时间排序</div>
        </div>
      </div>

      <div class="grid cols-2" style="margin-top: 16px">
        <div class="card">
          <div class="card-title">
            <span>即将截止的作业</span>
            <router-link class="small" :to="{ name: 'courses' }">全部课程</router-link>
          </div>
          <div v-if="!(data.upcoming || []).length" class="empty">暂无即将截止的作业</div>
          <div
            v-for="item in data.upcoming"
            :key="item.id"
            class="row between"
            style="padding: 8px 0; border-bottom: 1px solid var(--border)"
          >
            <div>
              <div>{{ item.title }}</div>
              <div class="faint small">{{ item.class_name }}</div>
            </div>
            <span class="badge yellow">{{ deadlineText(item.deadline) }}</span>
          </div>
        </div>

        <div class="card">
          <div class="card-title"><span>我的教学班</span></div>
          <div v-if="!data.classes.length" class="empty">还没有教学班，去课程页新建</div>
          <div
            v-for="item in data.classes"
            :key="item.id"
            class="row between"
            style="padding: 9px 0; border-bottom: 1px solid var(--border); cursor: pointer"
            @click="openClass(item.id)"
          >
            <div>
              <div>{{ item.class_name }}</div>
              <div class="faint small">{{ item.course_name }} · 邀请码 {{ item.join_code }}</div>
            </div>
            <span class="badge blue">{{ item.student_count }} 人</span>
          </div>
        </div>
      </div>
    </template>

    <!-- ================= 学生 ================= -->
    <template v-else-if="auth.isStudent && data">
      <div class="grid cols-4">
        <div class="stat">
          <div class="stat-label">在读课程</div>
          <div class="stat-value">{{ data.enrolled_classes }}</div>
          <div class="stat-hint">已加入的教学班</div>
        </div>
        <div class="stat">
          <div class="stat-label">待完成作业</div>
          <div class="stat-value" :style="{ color: pending.length ? 'var(--warning)' : '' }">
            {{ data.pending_assignments }}
          </div>
          <div class="stat-hint">未提交的作业</div>
        </div>
        <div class="stat">
          <div class="stat-label">出勤率</div>
          <div class="stat-value">{{ data.attendance.rate }}%</div>
          <div class="stat-hint">正常 {{ data.attendance.present }} / {{ data.attendance.total }}</div>
        </div>
        <div class="stat">
          <div class="stat-label">作业均分</div>
          <div class="stat-value">
            {{ data.average_score === null ? '—' : data.average_score }}
          </div>
          <div class="stat-hint">已批改的提交</div>
        </div>
      </div>

      <div v-if="openSessions.length" class="card" style="margin-top: 16px; border-color: rgba(63,185,80,.45)">
        <div class="card-title">
          <span style="color: var(--success)">有 {{ openSessions.length }} 个签到进行中</span>
          <router-link class="small" :to="{ name: 'attendance' }">去签到</router-link>
        </div>
        <div v-for="item in openSessions" :key="item.id" class="row between" style="padding: 6px 0">
          <div>
            <div>{{ item.title }}</div>
            <div class="faint small">{{ item.course_name }} · {{ item.class_name }}</div>
          </div>
          <span class="badge green">进行中</span>
        </div>
      </div>

      <div class="grid cols-2" style="margin-top: 16px">
        <div class="card">
          <div class="card-title">
            <span>待交作业</span>
            <router-link class="small" :to="{ name: 'my-assignments' }">全部</router-link>
          </div>
          <div v-if="!pending.length" class="empty">太棒了，没有待交作业</div>
          <div
            v-for="item in pending.slice(0, 5)"
            :key="item.id"
            class="row between"
            style="padding: 8px 0; border-bottom: 1px solid var(--border); cursor: pointer"
            @click="router.push({ name: 'assignment-detail', params: { id: item.id } })"
          >
            <div>
              <div>{{ item.title }}</div>
              <div class="faint small">{{ item.course_name }}</div>
            </div>
            <span class="badge yellow">{{ deadlineText(item.deadline) }}</span>
          </div>
        </div>

        <div class="card">
          <div class="card-title">
            <span>最近通知</span>
            <router-link class="small" :to="{ name: 'notifications' }">全部</router-link>
          </div>
          <div v-if="!notices.length" class="empty">暂无通知</div>
          <div
            v-for="item in notices"
            :key="item.id"
            class="row between"
            style="padding: 8px 0; border-bottom: 1px solid var(--border); gap: 10px"
          >
            <div style="min-width: 0">
              <div class="row" style="gap: 6px">
                <span
                  v-if="!item.is_read"
                  class="badge blue"
                  style="padding: 0 5px; font-size: 10px"
                >
                  新
                </span>
                <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                  {{ item.title }}
                </span>
              </div>
              <div class="faint small">{{ relativeTime(item.created_at) }}</div>
            </div>
            <span class="badge gray">{{ item.category }}</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
