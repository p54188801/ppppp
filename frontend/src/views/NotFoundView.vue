<script setup>
/**
 * 404 页面
 *
 * 当访问的路由不存在时展示，提示用户检查地址并提供回到工作台的入口。
 */
import { useRouter } from 'vue-router'

const router = useRouter()

function backHome() {
  router.push({ name: 'dashboard' })
}
</script>

<template>
  <div>
    <div class="card" style="max-width: 520px; margin: 8vh auto; text-align: center; padding: 40px 28px">
      <div class="stat-value" style="font-size: 64px; letter-spacing: 2px; color: var(--primary)">
        404
      </div>
      <h1 style="font-size: 19px; margin: 10px 0 6px; font-weight: 650">页面走丢了</h1>
      <p class="muted" style="margin: 0 0 20px">
        你访问的页面不存在或已被移除，请检查地址后重试。
      </p>
      <div class="row" style="justify-content: center">
        <button class="btn primary" @click="backHome">返回工作台</button>
        <button class="btn" @click="router.back()">返回上一页</button>
      </div>
    </div>
  </div>
</template>
