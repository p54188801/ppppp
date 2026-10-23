import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { onUnauthorized } from './api/client'
import './styles/main.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)

onUnauthorized(() => {
  // 令牌失效时统一回到登录页，避免每个页面各写一遍
  if (router.currentRoute.value.name !== 'login') {
    router.replace({ name: 'login' })
  }
})

app.config.errorHandler = (error, _instance, info) => {
  // 兜底：组件里没 catch 的异常至少能在控制台看到上下文
  console.error('[EduFlow] 未捕获异常', info, error)
}

app.mount('#app')
