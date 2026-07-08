// src/pages/Home.tsx
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useLang } from '../i18n/LanguageContext'

export default function Home() {
  const navigate = useNavigate()
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)
  const { t } = useLang()

  const FEATURES = [
    { icon: '🔍', title: t('home.feature1Title'), desc: t('home.feature1Desc') },
    { icon: '⚠️', title: t('home.feature2Title'), desc: t('home.feature2Desc') },
    { icon: '📋', title: t('home.feature3Title'), desc: t('home.feature3Desc') },
  ]

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
            {t('home.badge')}
          </div>
          <h1 style={{ fontSize: 40, fontWeight: 800, lineHeight: 1.25, margin: 0, whiteSpace: 'nowrap' }}>
            {t('home.heroLine1')} <span style={{ color: '#22C9DB' }}>{t('home.heroHighlight')}</span>{t('home.heroLine2')} {t('home.heroLine3')}
          </h1>
          <p
            style={{
              fontSize: 17,
              lineHeight: 1.6,
              color: 'rgba(255,255,255,0.75)',
              marginTop: 20,
            }}
          >
            {t('home.heroDesc1')}
            <br />
            {t('home.heroDesc2')}
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
            {isLoggedIn ? t('home.ctaLoggedIn') : t('home.ctaLoggedOut')}
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
          {t('home.featuresTitle')}
        </h2>
        <p style={{ textAlign: 'center', color: '#64748B', fontSize: 14, marginBottom: 40 }}>
          {t('home.featuresSub')}
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