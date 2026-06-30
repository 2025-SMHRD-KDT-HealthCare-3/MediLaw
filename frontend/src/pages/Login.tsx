import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { login } from '../api/auth'
import { useAuthStore } from '../store/authStore'
import { useLang } from '../i18n/LanguageContext'

export default function Login() {
  const { t } = useLang()
  const [loginId, setLoginId] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const setLoggedIn = useAuthStore((s) => s.login)

  const handleLogin = async () => {
    setError('')
    if (!loginId.trim() || !password.trim()) {
      setError(t('login.errEmpty'))
      return
    }
    try {
      const result = await login({ login_id: loginId, password })
      console.log('login result:', result)
      setLoggedIn()
      navigate('/chat')
    } catch (err: any) {
      setError(err.response?.data?.message ?? t('login.errFailed'))
      console.error('login error:', err)
    }
  }

  

  return (
    <div className="min-h-screen flex">
      <div className="hidden md:flex md:w-1/2 bg-navy flex-col justify-center px-16 text-white">
        <h1 className="text-5xl font-bold text-aqua mb-4">MediLaw AI</h1>
        <p className="text-xl text-slate-300 mb-2">{t('login.brandTagline')}</p>
        <p className="text-base text-slate-400">{t('login.brandSub')}</p>
        <div className="mt-12 space-y-3 text-sm text-slate-400">
          <p>{t('login.feature1')}</p>
          <p>{t('login.feature2')}</p>
          <p>{t('login.feature3')}</p>
        </div>
      </div>

      <div className="flex-1 flex flex-col justify-center items-center px-8 bg-white">
        <div className="w-full max-w-sm">
          <h2 className="text-2xl font-bold text-navy mb-8">{t('login.title')}</h2>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">{t('login.idLabel')}</label>
              <input
                type="text"
                value={loginId}
                onChange={(e) => setLoginId(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
                placeholder={t('login.idPlaceholder')}
                className="w-full px-4 py-2.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-aqua focus:border-transparent"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">{t('login.pwLabel')}</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
                placeholder={t('login.pwPlaceholder')}
                className="w-full px-4 py-2.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-aqua focus:border-transparent"
              />
            </div>

            {error ? <p className="text-sm text-error">{error}</p> : null}

            <button
              onClick={handleLogin}
              className="w-full py-2.5 bg-navy text-white font-medium rounded-lg hover:bg-aqua hover:text-navy transition-colors"
            >
              {t('login.submit')}
            </button>


          </div>

          <p className="mt-6 text-center text-sm text-slate-500">
            {t('login.noAccount')}{' '}
            <Link to="/signup" className="text-brand-blue font-medium hover:underline">{t('login.signupLink')}</Link>
          </p>

          <p className="mt-12 text-xs text-slate-400 text-center leading-relaxed">
            {t('login.disclaimer')}
          </p>
        </div>
      </div>
    </div>
  )
}