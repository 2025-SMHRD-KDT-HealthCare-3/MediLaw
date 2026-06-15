import express from 'express'
import cors from 'cors'
import 'dotenv/config'

const app = express()
const PORT = process.env.PORT ?? 4000

app.use(cors())
app.use(express.json())

// 헬스 체크
app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok' })
})

app.listen(PORT, () => {
  console.log(`[backend] http://localhost:${PORT}`)
})
