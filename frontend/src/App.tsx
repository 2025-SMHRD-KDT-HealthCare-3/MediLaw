import { Routes, Route, Link, useNavigate } from 'react-router-dom'
import Login from './pages/Login'
import Chat from './pages/Chat'
import Dashboard from './pages/Dashboard'
import MyPage from './pages/MyPage'
import ProtectedRoute from './components/ProtectedRoute'
import { useAuthStore } from './store/authStore'
import AdReview from './pages/AdReview'
import Signup from './pages/Signup'

function App() {
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)
  const logout = useAuthStore((s) => s.logout)
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()              // 로그인 깃발 내리기
    navigate('/login')    // 로그인 화면으로
  }

  return (
    <div>
      <nav className="flex items-center gap-4 p-4 bg-navy text-white">
        {isLoggedIn ? (
          <>
            <Link to="/chat" className="hover:text-aqua">챗봇</Link>
            <Link to="/dashboard" className="hover:text-aqua">대시보드</Link>
            <Link to="/ad-review" className="hover:text-aqua">광고검토</Link>
            <Link to="/mypage" className="hover:text-aqua">마이페이지</Link>
            <button onClick={handleLogout} className="ml-auto hover:text-aqua">
              로그아웃
            </button>
          </>
        ) : (
          <Link to="/login" className="hover:text-aqua">로그인</Link>
        )}
      </nav>

      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/chat" element={<ProtectedRoute><Chat /></ProtectedRoute>} />
        <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
        <Route path="/ad-review" element={<ProtectedRoute><AdReview /></ProtectedRoute>} />
        <Route path="/mypage" element={<ProtectedRoute><MyPage /></ProtectedRoute>} />
        <Route path="/" element={<div className="p-8 text-2xl text-navy">홈 — 위 메뉴를 클릭하세요</div>} />
      </Routes>
    </div>
  )
}

export default App