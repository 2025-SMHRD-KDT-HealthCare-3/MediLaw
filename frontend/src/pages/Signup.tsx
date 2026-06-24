import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { signup } from '../api/auth'

export default function Signup() {
  const [form, setForm] = useState({
    login_id: '',
    password: '',
    passwordConfirm: '',
    name: '',
    email: '',
    phone_number: '',
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const update = (key: string, value: string) =>
    setForm({ ...form, [key]: value })

  const handleSignup = async () => {
    setError('')

    // 간단한 입력 검증
    if (!form.login_id.trim() || !form.password.trim() || !form.name.trim()) {
      setError('아이디, 비밀번호, 이름은 필수입니다.')
      return
    }
    if (form.password.length < 8) {
      setError('비밀번호는 8자 이상이어야 합니다.')
      return
    }
    if (form.password !== form.passwordConfirm) {
      setError('비밀번호가 일치하지 않습니다.')
      return
    }

    setLoading(true)
    try {
      await signup({
        login_id: form.login_id,
        password: form.password,
        name: form.name,
        email: form.email,
        phone_number: form.phone_number,
      })
      alert('회원가입이 완료되었습니다. 로그인해주세요.')
      navigate('/login')
    } catch (err: any) {
      setError(err.response?.data?.message ?? '회원가입에 실패했습니다.')
      console.error('signup error:', err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F7F8FA] px-8 py-12">
      <div className="w-full max-w-sm">
        <h1 className="text-3xl font-bold text-aqua mb-1">MediLaw AI</h1>
        <h2 className="text-xl font-bold text-navy mb-8">회원가입</h2>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">아이디 *</label>
            <input
              value={form.login_id}
              onChange={(e) => update('login_id', e.target.value)}
              placeholder="사용할 아이디"
              className="w-full px-4 py-2.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-aqua focus:border-transparent"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">비밀번호 *</label>
            <input
              type="password"
              value={form.password}
              onChange={(e) => update('password', e.target.value)}
              placeholder="비밀번호"
              className="w-full px-4 py-2.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-aqua focus:border-transparent"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">비밀번호 확인 *</label>
            <input
              type="password"
              value={form.passwordConfirm}
              onChange={(e) => update('passwordConfirm', e.target.value)}
              placeholder="비밀번호 재입력"
              className="w-full px-4 py-2.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-aqua focus:border-transparent"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">이름 *</label>
            <input
              value={form.name}
              onChange={(e) => update('name', e.target.value)}
              placeholder="이름"
              className="w-full px-4 py-2.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-aqua focus:border-transparent"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">이메일</label>
            <input
              type="email"
              value={form.email}
              onChange={(e) => update('email', e.target.value)}
              placeholder="you@example.com"
              className="w-full px-4 py-2.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-aqua focus:border-transparent"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">연락처</label>
            <input
              value={form.phone_number}
              onChange={(e) => update('phone_number', e.target.value)}
              placeholder="01012345678"
              className="w-full px-4 py-2.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-aqua focus:border-transparent"
            />
          </div>

          {error && <p className="text-sm text-error">{error}</p>}

          <button
            onClick={handleSignup}
            disabled={loading}
            className="w-full py-2.5 bg-navy text-white font-medium rounded-lg hover:bg-aqua hover:text-navy transition-colors disabled:opacity-50"
          >
            {loading ? '가입 중…' : '회원가입'}
          </button>
        </div>

        <p className="mt-6 text-center text-sm text-slate-500">
          이미 계정이 있으신가요?{' '}
          <Link to="/login" className="text-brand-blue font-medium hover:underline">로그인</Link>
        </p>
      </div>
    </div>
  )
}