import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { login } from '../api/auth'

export default function Login() {
  const [loginId, setLoginId] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const handleLogin = async () => {
    setError('')
    if (!loginId.trim() || !password.trim()) {
      setError('아이디와 비밀번호를 입력하세요.')
      return
    }
    try {
      const result = await login({ login_id: loginId, password })
      console.log('login result:', result)
      navigate('/chat') // 로그인 성공 → 챗봇으로
    } catch (err: any) {
      setError(err.response?.data?.message ?? '로그인에 실패했습니다.')
      console.error('login error:', err)
    }
  }

  return (
    <div className="min-h-screen flex">
      <div className="hidden md:flex md:w-1/2 bg-navy flex-col justify-center px-16 text-white">
        <h1 className="text-5xl font-bold text-aqua mb-4">MediLaw AI</h1>
        <p className="text-xl text-slate-300 mb-2">의료·헬스케어 특화 AI 법령 도우미</p>
        <p className="text-base text-slate-400">근거 기반 답변과 조문 자동 검증</p>
        <div className="mt-12 space-y-3 text-sm text-slate-400">
          <p>✓ 실제 법령 데이터 기반 답변</p>
          <p>✓ 조문 인용 자동 검증 (Citation Firewall)</p>
          <p>✓ 법령 개정 실시간 추적</p>
        </div>
      </div>

      <div className="flex-1 flex flex-col justify-center items-center px-8 bg-white">
        <div className="w-full max-w-sm">
          <h2 className="text-2xl font-bold text-navy mb-8">로그인</h2>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">아이디</label>
              <input
                type="text"
                value={loginId}
                onChange={(e) => setLoginId(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
                placeholder="아이디를 입력하세요"
                className="w-full px-4 py-2.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-aqua focus:border-transparent"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">비밀번호</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
                placeholder="••••••••"
                className="w-full px-4 py-2.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-aqua focus:border-transparent"
              />
            </div>

            {error && <p className="text-sm text-error">{error}</p>}

            <button
              onClick={handleLogin}
              className="w-full py-2.5 bg-navy text-white font-medium rounded-lg hover:bg-aqua hover:text-navy transition-colors"
            >
              로그인
            </button>
          </div>

          <p className="mt-6 text-center text-sm text-slate-500">
            계정이 없으신가요?{' '}
            <Link to="/signup" className="text-brand-blue font-medium hover:underline">회원가입</Link>
          </p>

          <p className="mt-12 text-xs text-slate-400 text-center leading-relaxed">
            본 서비스는 법률 자문이 아니며, 중요한 의사결정 전 변호사 등 전문가의 검토가 필요합니다.
          </p>
        </div>
      </div>
    </div>
  )
}