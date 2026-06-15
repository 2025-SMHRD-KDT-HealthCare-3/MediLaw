# MediLaw AI

의료법 Legal AI (RAG + Citation Verification) 프로젝트.

## 디렉터리 구조

```
.
├── frontend/   # React 18 + Vite + TypeScript (포트 5173)
└── backend/    # Node 20 + Express + TypeScript (포트 4000)
```

## 시작하기

각 폴더에서 독립적으로 작업합니다. (모듈은 각자 `npm install`)

### 프론트엔드
```bash
cd frontend
npm install
npm run dev
```

### 백엔드
```bash
cd backend
cp .env.example .env
npm install
npm run dev
```

프론트엔드의 `/api/*` 요청은 Vite 프록시로 백엔드(4000)로 전달됩니다.

## 브랜치 전략

- `master`  : 배포 가능한 안정 버전
- `develop` : 통합 개발 브랜치 (기능 브랜치의 베이스)
- `b` : 개인/기능 작업 브랜치 → `develop` 으로 PR

예) 프론트 담당:
```bash
git checkout develop
git checkout -b front
```
