import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 프록시 대상(백엔드 node-bridge) 주소.
// - 로컬에서 직접 실행: 기본값 localhost:4000 사용(같은 PC에서 백엔드 띄울 때).
//   다른 PC의 백엔드를 쓰려면 이 값을 그 PC IP:4000 으로 바꾸면 됨.
// - 도커(compose)로 실행: 환경변수 VITE_PROXY_TARGET=http://node:4000 이 자동 주입됨.
const PROXY_TARGET = process.env.VITE_PROXY_TARGET ?? 'http://localhost:4000'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    host: true,   // 도커 컨테이너 밖(호스트)에서도 접속 가능하도록 0.0.0.0 바인딩
    port: 5173,
    // 도커 + 윈도우 바인드마운트에선 파일변경 이벤트가 안 와서 HMR(핫리로드)이 안 먹는다.
    // compose 가 VITE_USE_POLLING=1 을 주입하면 폴링으로 감지(로컬 직접 실행 땐 영향 없음).
    watch: process.env.VITE_USE_POLLING ? { usePolling: true } : undefined,
    proxy: {
      '/api': {
        target: PROXY_TARGET,
        changeOrigin: true,
        secure: false,
      },
    },
  },
})