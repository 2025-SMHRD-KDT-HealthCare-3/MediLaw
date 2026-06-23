# node-bridge (프론트 ↔ 백엔드 중계기). 포트 4000.
# 빌드 컨텍스트는 backend/node/ 이다.
FROM node:22-slim

WORKDIR /app

# 의존성 먼저 설치(레이어 캐시). package.json / package-lock.json 만 먼저 복사.
# npm ci: lock 파일대로 정확히 설치 → 팀원 간 버전 흔들림 없음(재현성).
COPY package*.json ./
RUN npm ci

# 소스 복사 (src/, tsconfig.json 등)
COPY . .

EXPOSE 4000

# dev 스크립트(tsx watch)로 기동. 대상 서버 주소는 compose 의 환경변수로 주입.
CMD ["npm", "run", "dev"]
