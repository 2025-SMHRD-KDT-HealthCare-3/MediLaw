import { useState, useRef, type RefObject } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { signup } from '../api/auth'
import { useLang } from '../i18n/LanguageContext'

const initial = {
  login_id: '',
  password: '',
  passwordConfirm: '',
  name: '',
  email: '',
  phone_number: '',
}

// 칸별 검증 규칙 한 곳에 모으기 (번역키를 반환, 통과 시 빈 문자열)
function validateField(name: string, form: typeof initial): string {
  switch (name) {
    case 'login_id':
      return !form.login_id.trim()
        ? 'signup.errIdRequired'
        : form.login_id.trim().length < 3
        ? 'signup.errIdShort'
        : ''
    case 'password':
      return !form.password
        ? 'signup.errPwRequired'
        : form.password.length < 8
        ? 'signup.errPwShort'
        : ''
    case 'passwordConfirm':
      return form.passwordConfirm !== form.password ? 'signup.errPwMismatch' : ''
    case 'name':
      return !form.name.trim() ? 'signup.errNameRequired' : ''
    case 'email':
      return form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)
        ? 'signup.errEmailInvalid'
        : ''
    default:
      return ''
  }
}

export default function Signup() {
  const { t } = useLang()
  const [form, setForm] = useState(initial)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  // 각 칸 포커스 이동용 ref
  const refs: Record<string, RefObject<HTMLInputElement | null>> = {
    login_id: useRef<HTMLInputElement>(null),
    password: useRef<HTMLInputElement>(null),
    passwordConfirm: useRef<HTMLInputElement>(null),
    name: useRef<HTMLInputElement>(null),
    email: useRef<HTMLInputElement>(null),
  }

  const update = (key: string, value: string) => {
    setForm((prev) => {
      const next = { ...prev, [key]: value }
      // 이미 에러난 칸은 입력 즉시 재검증 (고치면 바로 사라지게)
      if (errors[key]) {
        setErrors((e) => ({ ...e, [key]: validateField(key, next) }))
      }
      // 비밀번호 바꾸면 확인칸도 재검증
      if (key === 'password' && errors.passwordConfirm) {
        setErrors((e) => ({ ...e, passwordConfirm: validateField('passwordConfirm', next) }))
      }
      return next
    })
  }

  // 칸 벗어날 때(blur) 검증
  const handleBlur = (key: string) => {
    setErrors((e) => ({ ...e, [key]: validateField(key, form) }))
  }

  const handleSignup = async () => {
    setErrors((e) => ({ ...e, form: '' }))

    // 전체 검증
    const names = ['login_id', 'password', 'passwordConfirm', 'name', 'email']
    const next: Record<string, string> = {}
    names.forEach((n) => {
      const m = validateField(n, form)
      if (m) next[n] = m
    })
    setErrors(next)

    // 첫 에러 칸으로 포커스 이동
    const firstErr = names.find((n) => next[n])
    if (firstErr) {
      refs[firstErr]?.current?.focus()
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
      alert(t('signup.done'))
      navigate('/login')
    } catch (err: any) {
      const m = err.response?.data?.message ?? ''
      const key = m.includes('login_id')
        ? 'signup.errIdTaken'
        : m.includes('email')
        ? 'signup.errEmailTaken'
        : 'signup.errFailed'
      setErrors((p) => ({ ...p, form: key }))
      console.error('signup error:', err)
    } finally {
      setLoading(false)
    }
  }

  const inputClass = (key: string) =>
    `w-full px-4 py-2.5 border rounded-lg focus:outline-none focus:ring-2 focus:ring-aqua focus:border-transparent ${
      errors[key] ? 'border-error' : 'border-slate-300'
    }`

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F7F8FA] px-8 py-12">
      <div className="w-full max-w-sm">
        <h1 className="text-3xl font-bold text-aqua mb-1">MediLaw AI</h1>
        <h2 className="text-xl font-bold text-navy mb-8">{t('signup.title')}</h2>

        <div className="space-y-4">
          {/* 아이디 */}
          <div>
            <label htmlFor="login_id" className="block text-sm font-medium text-slate-700 mb-1">
              {t('signup.idLabel')}
            </label>
            <input
              id="login_id"
              ref={refs.login_id}
              value={form.login_id}
              onChange={(e) => update('login_id', e.target.value)}
              onBlur={() => handleBlur('login_id')}
              placeholder={t('signup.idPlaceholder')}
              aria-invalid={!!errors.login_id}
              aria-describedby="login_id-error"
              className={inputClass('login_id')}
            />
            {errors.login_id && (
              <p id="login_id-error" className="mt-1 text-xs text-error">{t(errors.login_id)}</p>
            )}
          </div>

          {/* 비밀번호 */}
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-slate-700 mb-1">
              {t('signup.pwLabel')}
            </label>
            <div className="relative">
              <input
                id="password"
                ref={refs.password}
                type={showPw ? 'text' : 'password'}
                value={form.password}
                onChange={(e) => update('password', e.target.value)}
                onBlur={() => handleBlur('password')}
                placeholder={t('signup.pwPlaceholder')}
                aria-invalid={!!errors.password}
                aria-describedby="password-help password-error"
                className={inputClass('password')}
              />
              <button
                type="button"
                onClick={() => setShowPw((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-500 hover:text-slate-700"
              >
                {showPw ? t('signup.hide') : t('signup.show')}
              </button>
            </div>
            <p id="password-help" className="mt-1 text-xs text-slate-400">{t('signup.pwHelp')}</p>
            {errors.password && (
              <p id="password-error" className="mt-1 text-xs text-error">{t(errors.password)}</p>
            )}
          </div>

          {/* 비밀번호 확인 */}
          <div>
            <label htmlFor="passwordConfirm" className="block text-sm font-medium text-slate-700 mb-1">
              {t('signup.pwConfirmLabel')}
            </label>
            <input
              id="passwordConfirm"
              ref={refs.passwordConfirm}
              type={showPw ? 'text' : 'password'}
              value={form.passwordConfirm}
              onChange={(e) => update('passwordConfirm', e.target.value)}
              onBlur={() => handleBlur('passwordConfirm')}
              placeholder={t('signup.pwConfirmPlaceholder')}
              aria-invalid={!!errors.passwordConfirm}
              aria-describedby="passwordConfirm-error"
              className={inputClass('passwordConfirm')}
            />
            {errors.passwordConfirm && (
              <p id="passwordConfirm-error" className="mt-1 text-xs text-error">{t(errors.passwordConfirm)}</p>
            )}
          </div>

          {/* 이름 */}
          <div>
            <label htmlFor="name" className="block text-sm font-medium text-slate-700 mb-1">
              {t('signup.nameLabel')}
            </label>
            <input
              id="name"
              ref={refs.name}
              value={form.name}
              onChange={(e) => update('name', e.target.value)}
              onBlur={() => handleBlur('name')}
              placeholder={t('signup.namePlaceholder')}
              aria-invalid={!!errors.name}
              aria-describedby="name-error"
              className={inputClass('name')}
            />
            {errors.name && (
              <p id="name-error" className="mt-1 text-xs text-error">{t(errors.name)}</p>
            )}
          </div>

          {/* 이메일 (선택) */}
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-slate-700 mb-1">
              {t('signup.emailLabel')} <span className="text-slate-400 font-normal">{t('signup.emailOptional')}</span>
            </label>
            <input
              id="email"
              ref={refs.email}
              type="email"
              value={form.email}
              onChange={(e) => update('email', e.target.value)}
              onBlur={() => handleBlur('email')}
              placeholder={t('signup.emailPlaceholder')}
              aria-invalid={!!errors.email}
              aria-describedby="email-error"
              className={inputClass('email')}
            />
            {errors.email && (
              <p id="email-error" className="mt-1 text-xs text-error">{t(errors.email)}</p>
            )}
          </div>

          {/* 연락처 (선택) */}
          <div>
            <label htmlFor="phone_number" className="block text-sm font-medium text-slate-700 mb-1">
              {t('signup.phoneLabel')} <span className="text-slate-400 font-normal">{t('signup.emailOptional')}</span>
            </label>
            <input
              id="phone_number"
              value={form.phone_number}
              onChange={(e) => update('phone_number', e.target.value)}
              placeholder={t('signup.phonePlaceholder')}
              className="w-full px-4 py-2.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-aqua focus:border-transparent"
            />
          </div>

          {/* 폼 전체 에러 (서버 실패 등) */}
          {errors.form && <p className="text-sm text-error">{t(errors.form)}</p>}

          <button
            onClick={handleSignup}
            disabled={loading}
            className="w-full py-2.5 bg-navy text-white font-medium rounded-lg hover:bg-aqua hover:text-navy transition-colors disabled:opacity-50"
          >
            {loading ? t('signup.submitting') : t('signup.submit')}
          </button>
        </div>

        <p className="mt-6 text-center text-sm text-slate-500">
          {t('signup.haveAccount')}{' '}
          <Link to="/login" className="text-brand-blue font-medium hover:underline">{t('signup.loginLink')}</Link>
        </p>
      </div>
    </div>
  )
}
