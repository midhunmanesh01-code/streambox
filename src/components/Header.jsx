import { Film, LogOut } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

export default function Header() {
  const { logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <header className="border-b border-stage-800/80 sticky top-0 z-20 bg-stage-950/85 backdrop-blur">
      <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Film className="w-4 h-4 text-brass-400" strokeWidth={1.5} />
          <span className="font-display text-lg tracking-marquee uppercase text-ink-100">Reel</span>
        </div>
        <button
          onClick={handleLogout}
          className="flex items-center gap-2 text-sm text-ink-500 hover:text-ink-100 transition-colors"
        >
          <LogOut className="w-4 h-4" strokeWidth={1.5} />
          Log Out
        </button>
      </div>
    </header>
  )
}
