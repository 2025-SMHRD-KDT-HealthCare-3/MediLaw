import cors from 'cors'
import cookieParser from 'cookie-parser'
import express from 'express'
import type { ErrorRequestHandler, NextFunction, Request, Response } from 'express'
import rateLimit from 'express-rate-limit'
import helmet from 'helmet'
import { createProxyMiddleware } from 'http-proxy-middleware'
import type { ClientRequest, IncomingMessage, ServerResponse } from 'node:http'
import type { Socket } from 'node:net'
import morgan from 'morgan'
import 'dotenv/config'

const app = express()
const PORT = process.env.PORT ?? 4000
const FRONTEND_ORIGIN = process.env.FRONTEND_ORIGIN ?? 'http://localhost:5173'
const FASTAPI_TARGET = process.env.FASTAPI_TARGET ?? 'http://127.0.0.1:8000'
const PRODUCT_API_TARGET = process.env.PRODUCT_API_TARGET ?? 'http://127.0.0.1:8001'
const HMS_API_KEY = process.env.HMS_API_KEY ?? ''
const PROD = process.env.NODE_ENV === 'production'

type SameSiteValue = 'lax' | 'strict' | 'none'
type ApiPayload = {
  success: boolean
  message: string
  code?: string
  data: unknown
}
type CookieRequest = Request & {
  cookies?: Record<string, string | undefined>
}
type ProxyErrorResponse = Response | ServerResponse | Socket

const positiveNumberEnv = (name: string, fallback: number) => {
  const value = Number(process.env[name] ?? fallback)
  return Number.isFinite(value) && value > 0 ? value : fallback
}

const booleanEnv = (name: string, fallback: boolean) => {
  const value = process.env[name]
  if (value === undefined) return fallback
  return ['1', 'true', 'yes', 'on'].includes(value.trim().toLowerCase())
}

const csvEnv = (name: string, fallback: string) => {
  const raw = process.env[name] ?? fallback
  const values = raw
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean)
  return values.length > 0 ? values : [fallback]
}

const sameSiteEnv = (name: string, fallback: SameSiteValue): SameSiteValue => {
  const value = process.env[name]?.trim().toLowerCase()
  return value === 'lax' || value === 'strict' || value === 'none' ? value : fallback
}

const ACCESS_TOKEN_EXPIRE_MINUTES = positiveNumberEnv('ACCESS_TOKEN_EXPIRE_MINUTES', 30)
const SESSION_COOKIE_MAX_AGE_MS = ACCESS_TOKEN_EXPIRE_MINUTES * 60_000
const LOGIN_TIMEOUT_MS = positiveNumberEnv('LOGIN_TIMEOUT_MS', 15_000)
const PRODUCT_PROXY_TIMEOUT_MS = positiveNumberEnv('PRODUCT_PROXY_TIMEOUT_MS', 190_000)
const RAG_PROXY_TIMEOUT_MS = positiveNumberEnv('RAG_PROXY_TIMEOUT_MS', 190_000)
const FRONTEND_ORIGINS = csvEnv('FRONTEND_ORIGIN', FRONTEND_ORIGIN)
const SESSION_COOKIE_SAME_SITE = sameSiteEnv('SESSION_COOKIE_SAME_SITE', 'lax')
const SESSION_COOKIE_SECURE = booleanEnv(
  'SESSION_COOKIE_SECURE',
  PROD || SESSION_COOKIE_SAME_SITE === 'none',
)

const sessionCookieOptions = {
  httpOnly: true,
  secure: SESSION_COOKIE_SECURE,
  sameSite: SESSION_COOKIE_SAME_SITE,
  path: '/',
} as const
const SESSION_COOKIE_SAME_SITE_HEADER =
  SESSION_COOKIE_SAME_SITE.charAt(0).toUpperCase() + SESSION_COOKIE_SAME_SITE.slice(1)
const EXPIRED_SESSION_COOKIE_HEADER = `session=; Path=/; HttpOnly; Max-Age=0; SameSite=${SESSION_COOKIE_SAME_SITE_HEADER}${
  SESSION_COOKIE_SECURE ? '; Secure' : ''
}`

const successPayload = (data: unknown = null, message = 'success'): ApiPayload => ({
  success: true,
  message,
  data,
})

const errorPayload = (message: string, code?: string, data: unknown = null): ApiPayload => ({
  success: false,
  message,
  code,
  data,
})

const errorField = (err: unknown, key: 'code' | 'name' | 'message') => {
  if (typeof err !== 'object' || err === null || !(key in err)) return undefined
  const value = (err as Record<string, unknown>)[key]
  return typeof value === 'string' ? value : undefined
}

const upstreamErrorCode = (err: unknown) => {
  const name = errorField(err, 'name')
  if (name === 'AbortError' || name === 'TimeoutError') return 'TIMEOUT'
  const code = errorField(err, 'code')
  if (code) return code
  if (typeof err === 'object' && err !== null && 'cause' in err) {
    const cause = (err as { cause?: unknown }).cause
    const causeCode = errorField(cause, 'code')
    if (causeCode) return causeCode
  }
  return 'ERROR'
}

const isMutatingMethod = (method: string) => !['GET', 'HEAD', 'OPTIONS'].includes(method)

const requestOrigin = (req: Request) => {
  const origin = req.get('origin')
  if (origin) return origin
  const referer = req.get('referer')
  if (!referer) return null
  try {
    return new URL(referer).origin
  } catch {
    return null
  }
}

const sessionOriginGuard = (req: Request, res: Response, next: NextFunction) => {
  const cookies = (req as CookieRequest).cookies
  if (!isMutatingMethod(req.method) || !cookies?.session) {
    next()
    return
  }

  const origin = requestOrigin(req)
  if (origin === null && !PROD) {
    next()
    return
  }
  if (origin !== null && FRONTEND_ORIGINS.includes(origin)) {
    next()
    return
  }

  res.status(403).json(errorPayload('요청 출처를 확인할 수 없습니다.', 'CSRF_ORIGIN_MISMATCH'))
}

const isExpressResponse = (res: ProxyErrorResponse): res is Response =>
  typeof (res as Response).status === 'function' && typeof (res as Response).json === 'function'

const isServerResponse = (res: ProxyErrorResponse): res is ServerResponse =>
  typeof (res as ServerResponse).writeHead === 'function' &&
  typeof (res as ServerResponse).setHeader === 'function'

const hasHeadersSent = (res: ProxyErrorResponse) =>
  'headersSent' in res && Boolean(res.headersSent)

const proxyErrorHandler = (err: unknown, req: IncomingMessage, res: ProxyErrorResponse) => {
  const errorCode = upstreamErrorCode(err)
  console.error('[proxy-error]', errorCode, req.url)
  if (hasHeadersSent(res)) return

  const statusCode = errorCode === 'ECONNREFUSED' ? 503 : 504
  const payload = errorPayload(
    '백엔드 서버에 연결할 수 없습니다. 잠시 후 다시 시도하세요.',
    `UPSTREAM_${errorCode}`,
  )

  if (isExpressResponse(res)) {
    res.status(statusCode).json(payload)
    return
  }

  if (isServerResponse(res)) {
    res.writeHead(statusCode, { 'Content-Type': 'application/json; charset=utf-8' })
    res.end(JSON.stringify(payload))
    return
  }

  res.end()
}

app.set('trust proxy', 1)
app.use(helmet())
app.use(
  cors({
    origin: FRONTEND_ORIGINS,
    credentials: true,
  }),
)
app.use(morgan(process.env.NODE_ENV === 'production' ? 'combined' : 'dev'))
app.use(cookieParser())
app.use('/api', sessionOriginGuard)

app.get('/api/health', (_req, res) => {
  res.json({
    status: 'ok',
    service: 'medilaw-node-bridge',
    session_cookie_max_age_minutes: SESSION_COOKIE_MAX_AGE_MS / 60_000,
    session_cookie: {
      same_site: SESSION_COOKIE_SAME_SITE,
      secure: SESSION_COOKIE_SECURE,
    },
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
    const data = (await upstream.json().catch(() => ({}))) as Record<string, unknown>
    const nestedData =
      typeof data.data === 'object' && data.data !== null
        ? (data.data as Record<string, unknown>)
        : undefined
    const token =
      typeof nestedData?.access_token === 'string'
        ? nestedData.access_token
        : typeof data.access_token === 'string'
          ? data.access_token
          : undefined

    if (upstream.ok && token) {
      res.cookie('session', token, {
        ...sessionCookieOptions,
        maxAge: SESSION_COOKIE_MAX_AGE_MS,
      })

      if (nestedData?.access_token) delete nestedData.access_token
      if (data?.access_token) delete data.access_token
    }

    res.status(upstream.status).json(data)
  } catch (err: unknown) {
    const errorCode = upstreamErrorCode(err)
    console.error('[auth-login-error]', errorCode, errorField(err, 'message'))
    res.status(errorCode === 'ECONNREFUSED' ? 503 : 504).json({
      ...errorPayload(
        '로그인 서버 응답이 지연되고 있습니다. 잠시 후 다시 시도하세요.',
        `UPSTREAM_${errorCode}`,
      ),
    })
  }
})

app.post('/api/auth/logout', (_req, res) => {
  res.clearCookie('session', sessionCookieOptions)
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
      proxyReq: (proxyReq: ClientRequest) => {
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
      proxyReq: (proxyReq: ClientRequest, req: IncomingMessage) => {
        const token = (req as CookieRequest).cookies?.session
        if (token) proxyReq.setHeader('Authorization', `Bearer ${token}`)
      },
      proxyRes: (proxyRes: IncomingMessage, _req: IncomingMessage, res: ServerResponse) => {
        if (proxyRes.statusCode === 401 && typeof res?.setHeader === 'function') {
          res.setHeader('Set-Cookie', EXPIRED_SESSION_COOKIE_HEADER)
        }
      },
      error: proxyErrorHandler,
    },
  }),
)

app.use((_req, res) => {
  res.status(404).json(errorPayload('경로를 찾을 수 없습니다.', 'NOT_FOUND'))
})

const appErrorHandler: ErrorRequestHandler = (err: unknown, _req, res, _next) => {
  console.error('[error]', err)
  if (res.headersSent) return

  const statusCode =
    typeof err === 'object' &&
    err !== null &&
    'status' in err &&
    typeof (err as { status?: unknown }).status === 'number'
      ? (err as { status: number }).status
      : 500
  const message = errorField(err, 'message') ?? String(err)

  res.status(statusCode).json({
    ...errorPayload(
      process.env.NODE_ENV === 'production' ? '서버 오류' : message,
      'INTERNAL',
    ),
  })
}

app.use(appErrorHandler)

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
