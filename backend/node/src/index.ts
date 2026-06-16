import cors from 'cors'
import express from 'express'
import { createProxyMiddleware } from 'http-proxy-middleware'
import 'dotenv/config'

const app = express()
const PORT = process.env.PORT ?? 4000
const FRONTEND_ORIGIN = process.env.FRONTEND_ORIGIN ?? 'http://localhost:5173'
const FASTAPI_TARGET = process.env.FASTAPI_TARGET ?? 'http://127.0.0.1:8000'
const PRODUCT_API_TARGET = process.env.PRODUCT_API_TARGET ?? 'http://127.0.0.1:8001'

app.use(
  cors({
    origin: FRONTEND_ORIGIN,
    credentials: true,
  }),
)

app.get('/api/health', (_req, res) => {
  res.json({
    status: 'ok',
    service: 'medilaw-node-bridge',
    targets: {
      rag: FASTAPI_TARGET,
      product: PRODUCT_API_TARGET,
    },
  })
})

app.use(
  '/api/rag',
  createProxyMiddleware({
    target: FASTAPI_TARGET,
    changeOrigin: true,
    ws: true,
    proxyTimeout: 0,
    timeout: 0,
    logger: console,
  }),
)

app.use(
  '/api',
  createProxyMiddleware({
    target: PRODUCT_API_TARGET,
    changeOrigin: true,
    ws: true,
    proxyTimeout: 0,
    timeout: 0,
    pathRewrite: (path) => `/api${path}`,
    logger: console,
  }),
)

app.listen(PORT, () => {
  console.log(`[node-bridge] http://localhost:${PORT}`)
  console.log(`[node-bridge] /api/rag/* -> ${FASTAPI_TARGET}`)
  console.log(`[node-bridge] /api/* -> ${PRODUCT_API_TARGET}`)
})
