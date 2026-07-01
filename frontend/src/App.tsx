import { Routes, Route, Link, useNavigate } from 'react-router-dom'
import Login from './pages/Login'
import Chat from './pages/Chat'
import MyPage from './pages/MyPage'
import ProtectedRoute from './components/ProtectedRoute'
import { useAuthStore } from './store/authStore'
import AdReview from './pages/AdReview'
import Signup from './pages/Signup'
import Home from './pages/Home'
import LawUpdates from './pages/LawUpdates'
import Checklist from './pages/Checklist'
import { useLang } from './i18n/LanguageContext'

function App() {
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)
  const logout = useAuthStore((s) => s.logout)
  const navigate = useNavigate()
  const { lang, toggle, t } = useLang()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const LangToggle = (
    <button
      onClick={toggle}
      title={t('nav.langSwitchTitle')}
      className="rounded-full border border-aqua px-3 py-1 text-sm font-medium text-aqua hover:bg-aqua hover:text-navy"
    >
      {lang === 'ko' ? t('nav.toggleToEn') : t('nav.toggleToKo')}
    </button>
  )

  return (
    <div>
      <nav className="flex items-center gap-4 p-4 bg-navy text-white">
        <Link to="/" className="font-bold hover:text-aqua">{t('nav.brand')}</Link>
        {isLoggedIn ? (
          <>
            <Link to="/chat" className="hover:text-aqua">{t('nav.chat')}</Link>
            <Link to="/ad-review" className="hover:text-aqua">{t('nav.adReview')}</Link>
            <Link to="/checklist" className="hover:text-aqua">{t('nav.checklist')}</Link>
            <Link to="/law-updates" className="hover:text-aqua">{t('nav.lawUpdates')}</Link>
            <Link to="/mypage" className="hover:text-aqua">{t('nav.mypage')}</Link>
            <div className="ml-auto flex items-center gap-3">
              {LangToggle}
              <button onClick={handleLogout} className="hover:text-aqua">
                {t('nav.logout')}
              </button>
            </div>
          </>
        ) : (
          <div className="ml-auto flex items-center gap-3">
            {LangToggle}
          </div>
        )}
      </nav>

      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/chat" element={<ProtectedRoute><Chat /></ProtectedRoute>} />
        <Route path="/ad-review" element={<ProtectedRoute><AdReview /></ProtectedRoute>} />
        <Route path="/checklist" element={<ProtectedRoute><Checklist /></ProtectedRoute>} />
        <Route path="/law-updates" element={<ProtectedRoute><LawUpdates /></ProtectedRoute>} />
        <Route path="/mypage" element={<ProtectedRoute><MyPage /></ProtectedRoute>} />
        <Route path="/" element={<Home />} />
      </Routes>
    </div>
  )
}

export default App