# MediLaw Node Bridge

Node bridge is the single backend entrypoint for the React app.

## Ports

| Service | Default URL | Notes |
| --- | --- | --- |
| React Vite | `http://localhost:5173` | Calls `/api/*`; Vite proxies to Node. |
| Node bridge | `http://localhost:4000` | Public API entrypoint for React. |
| HMS FastAPI RAG | `http://127.0.0.1:8000` | Preserved `backend/fastapi` service. |
| Product FastAPI app | `http://127.0.0.1:8001` | Preserved `backend/app` auth/rooms/chat service. |

## Environment

All values are optional.

```bash
PORT=4000
FRONTEND_ORIGIN=http://localhost:5173
FASTAPI_TARGET=http://127.0.0.1:8000
PRODUCT_API_TARGET=http://127.0.0.1:8001
HMS_API_KEY=
ACCESS_TOKEN_EXPIRE_MINUTES=30
SESSION_COOKIE_SAME_SITE=lax
SESSION_COOKIE_SECURE=false
LOGIN_TIMEOUT_MS=15000
PRODUCT_PROXY_TIMEOUT_MS=190000
RAG_PROXY_TIMEOUT_MS=190000
```

Do not commit `.env` files.

`ACCESS_TOKEN_EXPIRE_MINUTES` should match the product FastAPI setting. The bridge uses it as the `session` cookie max age.
`FRONTEND_ORIGIN` can be a comma-separated allowlist. Session cookie mutations with an existing cookie are checked against this origin list in production.
Set `SESSION_COOKIE_SAME_SITE=none` and `SESSION_COOKIE_SECURE=true` only when the frontend and Node bridge are deployed cross-site over HTTPS.
`HMS_API_KEY` is forwarded to the HMS FastAPI RAG service as `x-api-key`.
Timeout values are milliseconds. Product/RAG defaults allow long AI and PDF review calls while preventing requests from waiting forever.

## Routing

The bridge keeps product and RAG paths separate.

| React/Node path | Target | Upstream path |
| --- | --- | --- |
| `GET /api/health` | Node bridge | Local health response |
| `/api/rag/*` | HMS FastAPI RAG | `/*` |
| `/api/*` | Product FastAPI app | `/api/*` |

Examples:

```bash
curl http://localhost:4000/api/health
curl http://localhost:4000/api/rag/health
curl -X POST http://localhost:4000/api/rag/v1/retrieve -H "content-type: application/json" -d "{\"query\":\"medical advertising safety\",\"top_k\":3}"
curl -X POST http://localhost:4000/api/rag/documents/review -F "text=This treatment has no side effects and is one hundred percent safe."
curl http://localhost:4000/api/server-check
```

`Authorization` headers, multipart uploads, and SSE responses are forwarded as the original request stream. The bridge does not parse request bodies before proxying.

## Frontend API Map

프론트엔드는 기본적으로 `http://localhost:4000`의 Node bridge만 호출합니다.
Vite proxy를 쓰는 경우 프론트 코드에서는 host 없이 `/api/...` 경로만 사용하면 됩니다.

### Product API

회원, 인증, 방, 채팅 저장, DB 이력 조회처럼 서비스 데이터베이스와 연결되는 기능입니다.
Node bridge가 `backend/app` Product FastAPI 서버(`http://127.0.0.1:8001`)로 전달합니다.

| Method | Frontend path | 기능 |
| --- | --- | --- |
| `POST` | `/api/auth/signup` | 회원가입 |
| `POST` | `/api/auth/login` | 로그인, 세션 쿠키 발급 |
| `POST` | `/api/auth/logout` | 로그아웃, 세션 쿠키 삭제 |
| `GET` | `/api/users/me` | 내 사용자 정보 조회 |
| `PATCH` | `/api/users/me` | 내 사용자 정보 수정 |
| `POST` | `/api/rooms` | 상담/채팅방 생성 |
| `GET` | `/api/rooms` | 내 채팅방 목록 조회 |
| `GET` | `/api/rooms/{room_id}` | 채팅방 상세 조회 |
| `PATCH` | `/api/rooms/{room_id}` | 채팅방 정보 수정 |
| `POST` | `/api/rooms/{room_id}/leave` | 채팅방 나가기 |
| `POST` | `/api/rooms/{room_id}/close` | 채팅방 종료 |
| `DELETE` | `/api/rooms/{room_id}` | 채팅방 삭제 |
| `GET` | `/api/rooms/{room_id}/chats` | 채팅방 메시지 목록 조회 |
| `POST` | `/api/rooms/{room_id}/chats` | 사용자 메시지 저장 |
| `POST` | `/api/rooms/{room_id}/ai-answer` | 질문 저장 후 AI 답변 생성 및 저장 |
| `GET` | `/api/ai-ad-copies` | 광고 검토 이력 목록 조회 |
| `GET` | `/api/ai-ad-copies/{ai_copy_id}` | 광고 검토 이력 상세 조회 |
| `POST` | `/api/ai-ad-copies` | 텍스트 광고 검토 후 이력 저장 |
| `POST` | `/api/ai-ad-copies/ad-review` | 텍스트/PDF 광고 검토 후, 선택한 방에 결과 저장 |
| `GET` | `/api/answers/{ans_id}/evidences` | AI 답변의 근거 자료 조회 |
| `GET` | `/api/answers/{ans_id}/verifications` | AI 답변의 인용 검증 결과 조회 |
| `POST` | `/api/answers/{ans_id}/verify` | 특정 AI 답변 인용 검증 실행 |
| `POST` | `/api/verify` | 사용자가 입력한 인용 정보 검증 |

### RAG / HMS API

AI 검색, PDF 분석, 법령 개정 현황처럼 `backend/fastapi` HMS/RAG 서버가 처리하는 기능입니다.
Node bridge가 `http://127.0.0.1:8000`으로 전달하며, 프론트 경로에는 `/api/rag`가 붙습니다.

| Method | Frontend path | 기능 |
| --- | --- | --- |
| `GET` | `/api/rag/health` | HMS/RAG 서버 상태 확인 |
| `POST` | `/api/rag/chat` | AI 챗봇 단발 응답 생성 |
| `POST` | `/api/rag/chat/stream` | AI 챗봇 SSE 스트리밍 응답 생성 |
| `POST` | `/api/rag/documents/review` | PDF 또는 텍스트 문서 위험 분석, before/after 수정안 생성 |
| `POST` | `/api/rag/documents/review/stream` | PDF 문서 페이지별 스트리밍 분석 |
| `POST` | `/api/rag/chat/checklist` | 대화 및 PDF 분석 결과 기반 통합 체크리스트 생성 |
| `POST` | `/api/rag/v1/retrieve` | 법령/판례/가이드라인 하이브리드 검색 |
| `POST` | `/api/rag/v1/source-pack` | LLM 인용용 근거 묶음 생성 |
| `POST` | `/api/rag/v1/verify` | 법령/판례 인용 검증 |
| `GET` | `/api/rag/v1/statutes/search` | 법령 검색 |
| `GET` | `/api/rag/v1/laws/revisions` | 4대 법령 개정 현황 요약 조회 |
| `GET` | `/api/rag/v1/laws/{law_id}/revisions` | 특정 법령의 전체 개정 이력 조회 |
| `GET` | `/api/rag/v1/laws/diff?law_id=&from=&to=` | 두 시행일 버전의 조문 개정 전후 비교 |

### Common Frontend Examples

PDF 파일 분석:

```ts
const form = new FormData()
form.append('file', file)

const res = await fetch('/api/rag/documents/review', {
  method: 'POST',
  body: form,
})
const data = await res.json()
```

법령 개정 현황:

```ts
const res = await fetch('/api/rag/v1/laws/revisions')
const data = await res.json()
```

방에 저장되는 AI 답변:

```ts
const res = await fetch(`/api/rooms/${roomId}/ai-answer`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ question }),
})
const data = await res.json()
```

## Run Locally

Start the upstream services in separate terminals:

```bash
cd backend/fastapi
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Start the bridge:

```bash
cd backend/node
npm install
npm run dev
```

Start the frontend:

```bash
cd frontend
npm install
npm run dev
```
