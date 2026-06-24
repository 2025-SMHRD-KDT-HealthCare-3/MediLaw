// src/pages/Home.tsx
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'

const FEATURES = [
  {
    icon: '🔍',
    title: 'Citation Verification',
    desc: 'AI 답변의 근거 법령을 자동 검증하고, 확인·주의·오류 상태를 한눈에 보여줍니다.',
  },
  {
    icon: '⚠️',
    title: '위험 표현 감지',
    desc: '광고문구·문서 속 의료법 위반 소지 표현을 사전에 찾아내고 대안을 제시합니다.',
  },
  {
    icon: '📋',
    title: '컴플라이언스 리포트',
    desc: '검토 결과를 법령 기준일과 함께 기록해, 감사 추적이 가능한 문서로 남깁니다.',
  },
]

export default function Home() {
  const navigate = useNavigate()
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)

  const handleStart = () => {
    navigate(isLoggedIn ? '/chat' : '/login')
  }

  return (
    <div style={{ background: '#F7F8FA', minHeight: 'calc(100vh - 56px)' }}>
      {/* 히어로 */}
      <section
        style={{
          background: '#14304A',
          color: '#fff',
          padding: '72px 24px 80px',
          textAlign: 'center',
        }}
      >
        <div style={{ maxWidth: 720, margin: '0 auto' }}>
          <div
            style={{
              display: 'inline-block',
              fontSize: 13,
              fontWeight: 600,
              color: '#22C9DB',
              border: '1px solid rgba(34,201,219,0.4)',
              borderRadius: 999,
              padding: '5px 14px',
              marginBottom: 24,
            }}
          >
            의료법 컴플라이언스 AI
          </div>
          <h1 style={{ fontSize: 40, fontWeight: 800, lineHeight: 1.25, margin: 0 }}>
            답이 아니라 <span style={{ color: '#22C9DB' }}>상태</span>를<br />
            관리하는 도구
          </h1>
          <p
            style={{
              fontSize: 17,
              lineHeight: 1.6,
              color: 'rgba(255,255,255,0.75)',
              marginTop: 20,
            }}
          >
            의료 서비스 운영자를 위한 법률 질의응답과 위험 표현 검토.
            <br />
            근거를 검증하고, 컴플라이언스를 기록으로 남깁니다.
          </p>
          <button
            onClick={handleStart}
            style={{
              marginTop: 32,
              background: '#22C9DB',
              color: '#14304A',
              fontSize: 16,
              fontWeight: 700,
              border: 'none',
              borderRadius: 10,
              padding: '14px 32px',
              cursor: 'pointer',
            }}
          >
            {isLoggedIn ? '바로 시작하기 →' : '로그인하고 시작하기 →'}
          </button>
        </div>
      </section>

      {/* 핵심 기능 3카드 */}
      <section style={{ maxWidth: 980, margin: '0 auto', padding: '56px 24px 72px' }}>
        <h2
          style={{
            fontSize: 22,
            fontWeight: 700,
            color: '#14304A',
            textAlign: 'center',
            marginBottom: 8,
          }}
        >
          핵심 기능
        </h2>
        <p style={{ textAlign: 'center', color: '#64748B', fontSize: 14, marginBottom: 40 }}>
          ChatGPT와 다른, 의료법에 특화된 세 가지
        </p>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
            gap: 20,
          }}
        >
          {FEATURES.map((f) => (
            <div
              key={f.title}
              style={{
                background: '#fff',
                border: '1px solid #E2E8F0',
                borderRadius: 16,
                padding: '28px 24px',
              }}
            >
              <div style={{ fontSize: 30, marginBottom: 14 }}>{f.icon}</div>
              <h3 style={{ fontSize: 17, fontWeight: 700, color: '#14304A', margin: '0 0 10px' }}>
                {f.title}
              </h3>
              <p style={{ fontSize: 14, lineHeight: 1.6, color: '#64748B', margin: 0 }}>{f.desc}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}