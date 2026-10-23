import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

/**
 * 使用 hash 路由：pywebview 加载的是本地 http 服务，
 * hash 模式不需要服务端做 history 回退，部署到任何静态宿主都能跑。
 */
const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    name: 'dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { title: '工作台' },
  },
  {
    path: '/courses',
    name: 'courses',
    component: () => import('@/views/CourseListView.vue'),
    meta: { title: '课程' },
  },
  {
    path: '/courses/:id',
    name: 'course-detail',
    component: () => import('@/views/CourseDetailView.vue'),
    meta: { title: '课程详情' },
  },
  {
    path: '/classes/:id',
    name: 'class-detail',
    component: () => import('@/views/ClassDetailView.vue'),
    meta: { title: '教学班' },
  },
  {
    path: '/classes/:id/gradebook',
    name: 'gradebook',
    component: () => import('@/views/GradebookView.vue'),
    meta: { title: '成绩册', roles: ['teacher', 'admin'] },
  },
  {
    path: '/my/assignments',
    name: 'my-assignments',
    component: () => import('@/views/MyAssignmentsView.vue'),
    meta: { title: '我的作业', roles: ['student'] },
  },
  {
    path: '/assignments/:id',
    name: 'assignment-detail',
    component: () => import('@/views/AssignmentDetailView.vue'),
    meta: { title: '作业详情' },
  },
  {
    path: '/quizzes/:id/take',
    name: 'quiz-take',
    component: () => import('@/views/QuizTakeView.vue'),
    meta: { title: '在线测验', roles: ['student'] },
  },
  {
    path: '/attendance',
    name: 'attendance',
    component: () => import('@/views/AttendanceView.vue'),
    meta: { title: '签到' },
  },
  {
    path: '/grades',
    name: 'grades',
    component: () => import('@/views/TranscriptView.vue'),
    meta: { title: '我的成绩', roles: ['student'] },
  },
  {
    path: '/notifications',
    name: 'notifications',
    component: () => import('@/views/NotificationsView.vue'),
    meta: { title: '通知' },
  },
  {
    path: '/admin/users',
    name: 'admin-users',
    component: () => import('@/views/AdminUsersView.vue'),
    meta: { title: '用户管理', roles: ['admin'] },
  },
  {
    path: '/profile',
    name: 'profile',
    component: () => import('@/views/ProfileView.vue'),
    meta: { title: '个人中心' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { public: true, title: '页面不存在' },
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  document.title = to.meta.title ? `${to.meta.title} · EduFlow` : 'EduFlow'

  if (to.meta.public) return true

  if (!auth.token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (!auth.user) {
    try {
      await auth.fetchMe()
    } catch {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
  }
  if (to.meta.roles && !to.meta.roles.includes(auth.user.role)) {
    return { name: 'dashboard' }
  }
  return true
})

export default router
