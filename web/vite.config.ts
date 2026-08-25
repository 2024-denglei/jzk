import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // 若本机 8000 已被占用，可设环境变量 PORT=8010 启动后端
      '/api': process.env.VITE_API_PROXY || 'http://127.0.0.1:8010',
      '/health': process.env.VITE_API_PROXY || 'http://127.0.0.1:8010',
    },
  },
})
