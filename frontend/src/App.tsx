import { useEffect, useState } from 'react'

export default function App() {
  const [health, setHealth] = useState('확인 중...')

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then((d) => setHealth(d.status))
      .catch(() => setHealth('백엔드 연결 실패'))
  }, [])

  return (
    <main style={{ fontFamily: 'sans-serif', padding: 32 }}>
      <h1>MediLaw AI</h1>
      <p>백엔드 상태: {health}</p>
    </main>
  )
}
