import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    host: true,
    proxy: {
      '/api': {
        target: 'http://192.168.219.52:4000', // 백엔드 주소. IP 바뀌면 이 줄만 교체
        changeOrigin: true,
        secure: false,
      },
    },
  },
})