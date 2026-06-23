import cors from 'cors'
import cookieParser from 'cookie-parser'
import express from 'express'
import rateLimit from 'express-rate-limit'
import helmet from 'helmet'
import { createProxyMiddleware } from 'http-proxy-middleware'
import morgan from 'morgan'
import 'dotenv/config'

const app = express()
const PORT = process.env.PORT ?? 4000
const FRONTEND_ORIGIN = process.env.FRONTEND_ORIGIN ?? 'http://localhost:5173'
const FASTAPI_TARGET = process.env.FASTAPI_TARGET ?? 'http://127.0.0.1:8000'
const PRODUCT_API_TARGET = process.env.PRODUCT_API_TARGET ?? 'http://127.0.0.1:8001'
const HMS_API_KEY = process.env.HMS_API_KEY ?? ''
const PROD = process.env.NODE_ENV === 'production'

const positiveNumberEnv = (name: string, fallback: number) => {
  const value = Number(process.env[name] ?? fallback)
  return Number.isFinite(value) && value > 0 ? value : fallback
}

const ACCESS_TOKEN_EXPIRE_MINUTES = positiveNumberEnv('ACCESS_TOKEN_EXPIRE_MINUTES', 30)
const SESSION_COOKIE_MAX_AGE_MS = ACCESS_TOKEN_EXPIRE_MINUTES * 60_000
const LOGIN_TIMEOUT_MS = positiveNumberEnv('LOGIN_TIMEOUT_MS', 15_000)
const PRODUCT_PROXY_TIMEOUT_MS = positiveNumberEnv('PRODUCT_PROXY_TIMEOUT_MS', 190_000)
const RAG_PROXY_TIMEOUT_MS = positiveNumberEnv('RAG_PROXY_TIMEOUT_MS', 190_000)

const successPayload = (data: any = null, message = 'success') => ({
  success: true,
  message,
  data,
})

const errorPayload = (message: string, code?: string, data: any = null) => ({
  success: false,
  message,
  code,
  data,
})

const upstreamErrorCode = (err: any) => {
  if (err?.name === 'AbortError' || err?.name === 'TimeoutError') return 'TIMEOUT'
  return err?.code ?? err?.cause?.code ?? 'ERROR'
}

const proxyErrorHandler = (err: any, req: any, res: any) => {
  const errorCode = upstreamErrorCode(err)
  console.error('[proxy-error]', errorCode, req?.url)
  if (res?.headersSent) return

  const statusCode = errorCode === 'ECONNREFUSED' ? 503 : 504
  const payload = errorPayload(
    '백엔드 서버에 연결할 수 없습니다. 잠시 후 다시 시도하세요.',
    `UPSTREAM_${errorCode}`,
  )

  if (typeof res?.status === 'function' && typeof res?.json === 'function') {
    res.status(statusCode).json(payload)
    return
  }

  if (typeof res?.writeHead === 'function' && typeof res?.end === 'function') {
    res.writeHead(statusCode, { 'Content-Type': 'application/json; charset=utf-8' })
    res.end(JSON.stringify(payload))
  }
}

app.set('trust proxy', 1)
app.use(helmet())
app.use(
  cors({
    origin: FRONTEND_ORIGIN,
    credentials: true,
  }),
)
app.use(morgan(process.env.NODE_ENV === 'production' ? 'combined' : 'dev'))
app.use(cookieParser())

app.get('/api/health', (_req, res) => {
  res.json({
    status: 'ok',
    service: 'medilaw-node-bridge',
    session_cookie_max_age_minutes: SESSION_COOKIE_MAX_AGE_MS / 60_000,
    timeouts_ms: {
      login: LOGIN_TIMEOUT_MS,
      product: PRODUCT_PROXY_TIMEOUT_MS,
      rag: RAG_PROXY_TIMEOUT_MS,
    },
    targets: {
      rag: FASTAPI_TARGET,
      product: PRODUCT_API_TARGET,
    },
  })
})

const authLoginLimiter = rateLimit({
  windowMs: 60_000,
  limit: 10,
  standardHeaders: true,
  legacyHeaders: false,
})

app.post('/api/auth/login', authLoginLimiter, express.json(), async (req, res) => {
  try {
    const upstream = await fetch(`${PRODUCT_API_TARGET}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req.body),
      signal: AbortSignal.timeout(LOGIN_TIMEOUT_MS),
    })
    const data: any = await upstream.json().catch(() => ({}))
    const token = data?.data?.access_token ?? data?.access_token

    if (upstream.ok && token) {
      res.cookie('session', token, {
        httpOnly: true,
        secure: PROD,
        sameSite: 'lax',
        maxAge: SESSION_COOKIE_MAX_AGE_MS,
        path: '/',
      })

      if (data?.data?.access_token) delete data.data.access_token
      if (data?.access_token) delete data.access_token
    }

    res.status(upstream.status).json(data)
  } catch (err: any) {
    const errorCode = upstreamErrorCode(err)
    console.error('[auth-login-error]', errorCode, err?.message)
    res.status(errorCode === 'ECONNREFUSED' ? 503 : 504).json({
      ...errorPayload(
        '로그인 서버 응답이 지연되고 있습니다. 잠시 후 다시 시도하세요.',
        `UPSTREAM_${errorCode}`,
      ),
    })
  }
})

app.post('/api/auth/logout', (_req, res) => {
  res.clearCookie('session', { path: '/' })
  res.json(successPayload({ message: 'logged out' }))
})

app.use(
  '/api/rag',
  rateLimit({
    windowMs: 60_000,
    limit: 30,
    standardHeaders: true,
    legacyHeaders: false,
  }),
)

app.use(
  '/api',
  rateLimit({
    windowMs: 60_000,
    limit: 120,
    standardHeaders: true,
    legacyHeaders: false,
    skip: (req) => req.originalUrl.startsWith('/api/rag'),
  }),
)

app.use('/api/rag', (req, res, next) => {
  if (['/chat', '/chat/stream', '/chat/checklist'].includes(req.path)) {
    res.status(409).json(
      errorPayload(
        '챗봇 요청은 저장을 위해 product API를 통해 호출해야 합니다.',
        'RAG_DIRECT_CHAT_BLOCKED',
        { expected_path: '/api/rooms/{room_id}/ai-answer' },
      ),
    )
    return
  }
  next()
})

app.use(
  '/api/rag',
  createProxyMiddleware({
    target: FASTAPI_TARGET,
    changeOrigin: true,
    ws: true,
    proxyTimeout: RAG_PROXY_TIMEOUT_MS,
    timeout: RAG_PROXY_TIMEOUT_MS,
    logger: console,
    on: {
      proxyReq: (proxyReq: any) => {
        if (HMS_API_KEY) proxyReq.setHeader('x-api-key', HMS_API_KEY)
      },
      error: proxyErrorHandler,
    },
  }),
)

app.use(
  '/api',
  createProxyMiddleware({
    target: PRODUCT_API_TARGET,
    changeOrigin: true,
    ws: true,
    proxyTimeout: PRODUCT_PROXY_TIMEOUT_MS,
    timeout: PRODUCT_PROXY_TIMEOUT_MS,
    pathRewrite: (path) => `/api${path}`,
    logger: console,
    on: {
      proxyReq: (proxyReq: any, req: any) => {
        const token = req.cookies?.session
        if (token) proxyReq.setHeader('Authorization', `Bearer ${token}`)
      },
      proxyRes: (proxyRes: any, _req: any, res: any) => {
        if (proxyRes.statusCode === 401 && typeof res?.setHeader === 'function') {
          res.setHeader(
            'Set-Cookie',
            `session=; Path=/; HttpOnly; Max-Age=0; SameSite=Lax${PROD ? '; Secure' : ''}`,
          )
        }
      },
      error: proxyErrorHandler,
    },
  }),
)

app.use((_req, res) => {
  res.status(404).json(errorPayload('경로를 찾을 수 없습니다.', 'NOT_FOUND'))
})

app.use((err: any, _req: any, res: any, _next: any) => {
  console.error('[error]', err)
  if (res.headersSent) return

  res.status(err.status || 500).json({
    ...errorPayload(
      process.env.NODE_ENV === 'production' ? '서버 오류' : String(err?.message ?? err),
      'INTERNAL',
    ),
  })
})

const server = app.listen(PORT, () => {
  console.log(`[node-bridge] http://localhost:${PORT}`)
  console.log(`[node-bridge] /api/rag/* -> ${FASTAPI_TARGET}`)
  console.log(`[node-bridge] /api/* -> ${PRODUCT_API_TARGET}`)
})

process.on('unhandledRejection', (err) => {
  console.error('[unhandledRejection]', err)
})

process.on('uncaughtException', (err) => {
  console.error('[uncaughtException]', err)
})

for (const signal of ['SIGTERM', 'SIGINT'] as const) {
  process.on(signal, () => {
    server.close(() => process.exit(0))
  })
}
