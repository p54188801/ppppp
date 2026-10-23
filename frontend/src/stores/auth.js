import { defineStore } from 'pinia'
import { api, clearToken, getToken, setToken } from '@/api/client'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getToken(),
    user: null,
    loading: false,
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.token && state.user),
    role: (state) => (state.user ? state.user.role : ''),
    displayName: (state) => (state.user ? state.user.real_name : ''),
    roleLabel: (state) => (state.user ? state.user.role_label : ''),
    isAdmin: (state) => state.user && state.user.role === 'admin',
    isTeacher: (state) => state.user && ['teacher', 'admin'].includes(state.user.role),
    isStudent: (state) => state.user && state.user.role === 'student',
  },
  actions: {
    async login(username, password) {
      this.loading = true
      try {
        const data = await api.post('/api/auth/login', { username, password })
        this.token = data.token
        this.user = data.user
        setToken(data.token)
        return data.user
      } finally {
        this.loading = false
      }
    },
    async fetchMe() {
      if (!this.token) return null
      try {
        const user = await api.get('/api/auth/me')
        this.user = user
        return user
      } catch (error) {
        this.reset()
        throw error
      }
    },
    async logout() {
      try {
        await api.post('/api/auth/logout')
      } catch {
        /* 忽略登出失败 */
      }
      this.reset()
    },
    reset() {
      this.token = ''
      this.user = null
      clearToken()
    },
    canManageCourse(course) {
      if (!this.user || !course) return false
      if (this.user.role === 'admin') return true
      return this.user.role === 'teacher' && Number(course.teacher_id) === Number(this.user.id)
    },
  },
})
