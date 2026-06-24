import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getMe, updateMe } from '../api/auth'
import { useAuthStore } from '../store/authStore'

interface UserInfo {
  login_id?: string
  name?: string
  email?: string
  phone_number?: string
  role?: string
}

export default function MyPage() {
  const [user, setUser] = useState<UserInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState({ name: '', email: '', phone_number: '' })
  const [msg, setMsg] = useState('')
  const logout = useAuthStore((s) => s.logout)
  const navigate = useNavigate()

  useEffect(() => {
    const load = async () => {
      try {
        const res = await getMe()
        const data = res.data ?? res
        setUser(data)
        setForm({
          name: data.name ?? '',
          email: data.email ?? '',
          phone_number: data.phone_number ?? '',
        })
      } catch (err) {
        console.error('내 정보 로드 실패:', err)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const handleSave = async () => {
    setMsg('')
    try {
      await updateMe(form)
      setUser((prev) => ({ ...prev, ...form }))
      setEditing(false)
      setMsg('저장되었습니다.')
    } catch (err: any) {
      setMsg('저장 실패: ' + (err.response?.data?.message ?? err.message))
    }
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="min-h-screen bg-[#F7F8FA] p-8">
      <div className="mx-auto max-w-xl">
        <h1 className="text-2xl font-bold text-navy mb-1">마이페이지</h1>
        <p className="text-sm text-slate-500 mb-8">내 계정 정보를 확인하고 수정할 수 있습니다.</p>

        {loading ? (
          <p className="text-sm text-slate-400">불러오는 중…</p>
        ) : (
          <div className="rounded-xl border border-gray-200 bg-white p-6">
            {/* 아이디 (수정 불가) */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-slate-400 mb-1">아이디</label>
              <p className="text-sm text-slate-800">{user?.login_id ?? '-'}</p>
            </div>

            {/* 이름 */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-slate-400 mb-1">이름</label>
              {editing ? (
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-aqua focus:outline-none"
                />
              ) : (
                <p className="text-sm text-slate-800">{user?.name ?? '-'}</p>
              )}
            </div>

            {/* 이메일 */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-slate-400 mb-1">이메일</label>
              {editing ? (
                <input
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-aqua focus:outline-none"
                />
              ) : (
                <p className="text-sm text-slate-800">{user?.email ?? '-'}</p>
              )}
            </div>

            {/* 연락처 */}
            <div className="mb-6">
              <label className="block text-xs font-medium text-slate-400 mb-1">연락처</label>
              {editing ? (
                <input
                  value={form.phone_number}
                  onChange={(e) => setForm({ ...form, phone_number: e.target.value })}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-aqua focus:outline-none"
                />
              ) : (
                <p className="text-sm text-slate-800">{user?.phone_number ?? '-'}</p>
              )}
            </div>

            {msg && <p className="mb-4 text-sm text-teal-600">{msg}</p>}

            {/* 버튼 */}
            <div className="flex gap-2">
              {editing ? (
                <>
                  <button onClick={handleSave}
                    className="rounded-lg bg-navy px-5 py-2 text-sm font-medium text-white hover:bg-navy/90">
                    저장
                  </button>
                  <button onClick={() => setEditing(false)}
                    className="rounded-lg border border-slate-300 px-5 py-2 text-sm text-slate-600 hover:bg-slate-50">
                    취소
                  </button>
                </>
              ) : (
                <button onClick={() => setEditing(true)}
                  className="rounded-lg bg-navy px-5 py-2 text-sm font-medium text-white hover:bg-navy/90">
                  정보 수정
                </button>
              )}
              <button onClick={handleLogout}
                className="ml-auto rounded-lg border border-slate-300 px-5 py-2 text-sm text-slate-600 hover:bg-slate-50">
                로그아웃
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}