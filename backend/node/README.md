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
ACCESS_TOKEN_EXPIRE_MINUTES=30
LOGIN_TIMEOUT_MS=15000
PRODUCT_PROXY_TIMEOUT_MS=190000
RAG_PROXY_TIMEOUT_MS=190000
```

Do not commit `.env` files.

`ACCESS_TOKEN_EXPIRE_MINUTES` should match the product FastAPI setting. The bridge uses it as the `session` cookie max age.
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
