import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    proxy: {
      '/api': {
        target: 'http://192.168.219.54:4000', // 팀원 백엔드. IP 바뀌면 이 줄만 교체
        changeOrigin: true,
      },
    },
  },
})