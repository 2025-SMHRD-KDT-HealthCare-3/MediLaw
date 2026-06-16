import { Routes, Route, Link } from 'react-router-dom'
import Login from './pages/Login'
import Chat from './pages/Chat'
import Dashboard from './pages/Dashboard'
import MyPage from './pages/MyPage'

function App() {
  return (
    <div>
      {/* 임시 네비게이션 (테스트용) */}
      <nav className="flex gap-4 p-4 bg-navy text-white">
        <Link to="/login" className="hover:text-aqua">로그인</Link>
        <Link to="/chat" className="hover:text-aqua">챗봇</Link>
        <Link to="/dashboard" className="hover:text-aqua">대시보드</Link>
        <Link to="/mypage" className="hover:text-aqua">마이페이지</Link>
      </nav>

      {/* 경로별 페이지 */}
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/mypage" element={<MyPage />} />
        <Route path="/" element={<div className="p-8 text-2xl text-navy">홈 — 위 메뉴를 클릭하세요</div>} />
      </Routes>
    </div>
  )
}

export default App