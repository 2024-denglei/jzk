import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/admin/',
  server: {
    port: 5174,
    proxy: {
      // 后端固定跑在 8010，与 config.PORT、compose 和 Dockerfile 一致
      '/api': process.env.VITE_API_PROXY || 'http://127.0.0.1:8010',
      '/health': process.env.VITE_API_PROXY || 'http://127.0.0.1:8010',
    },
  },
})
