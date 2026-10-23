import { defineStore } from 'pinia'

let seed = 0

export const useUiStore = defineStore('ui', {
  state: () => ({
    toasts: [],
    confirmState: null,
  }),
  actions: {
    toast(message, type = 'info', timeout = 2600) {
      const id = ++seed
      this.toasts.push({ id, message, type })
      window.setTimeout(() => this.dismiss(id), timeout)
    },
    success(message) {
      this.toast(message, 'success')
    },
    error(message) {
      this.toast(message, 'error', 4200)
    },
    dismiss(id) {
      const index = this.toasts.findIndex((item) => item.id === id)
      if (index >= 0) this.toasts.splice(index, 1)
    },
    confirm(options) {
      const config = typeof options === 'string' ? { message: options } : options || {}
      return new Promise((resolve) => {
        this.confirmState = {
          title: config.title || '确认操作',
          message: config.message || '',
          confirmText: config.confirmText || '确定',
          danger: Boolean(config.danger),
          resolve,
        }
      })
    },
    resolveConfirm(value) {
      if (this.confirmState) {
        this.confirmState.resolve(value)
        this.confirmState = null
      }
    },
  },
})
