# frontend (React 19 + Vite 8). 개발 서버를 그대로 띄워 빠른 테스트에 사용. 포트 5173.
# 빌드 컨텍스트는 frontend/ 이다.
FROM node:22-slim

WORKDIR /app

# 의존성 먼저 설치(레이어 캐시). npm ci 로 lock 파일대로 정확히 설치(재현성).
COPY package*.json ./
RUN npm ci

# 소스 복사
COPY . .

EXPOSE 5173

# Vite dev 서버. vite.config.ts 의 server.host=true 로 0.0.0.0 바인딩되어 호스트에서 접속 가능.
# 프록시 대상(node-bridge)은 compose 의 VITE_PROXY_TARGET 환경변수로 주입.
CMD ["npm", "run", "dev"]
