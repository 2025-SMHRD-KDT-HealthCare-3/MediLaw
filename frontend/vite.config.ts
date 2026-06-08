import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 프론트(5173) → 백엔드(4000) API 프록시
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:4000',
    },
  },
})
