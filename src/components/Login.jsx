import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Eye, EyeOff, Film, Lock } from 'lucide-react'
import { useAuth } from '../context/AuthContext.jsx'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    const result = await login(username, password)
    setSubmitting(false)
    if (result.ok) {
      navigate(location.state?.from || '/', { replace: true })
    } else {
      setError(result.error)
    }
  }

  return (
    <div className="min-h-screen bg-stage-950 relative overflow-hidden flex items-center justify-center px-6">
      {/* ambient backdrop */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -top-40 left-1/2 -translate-x-1/2 w-[600px] h-[600px] rounded-full bg-brass-600/10 blur-3xl" />
        <div className="absolute inset-0 film-grain animate-grain opacity-[0.04]" />
      </div>

      <div className="relative w-full max-w-sm animate-rise">
        <div className="flex flex-col items-center mb-10">
          <div className="w-11 h-11 rounded-full border border-brass-400/40 flex items-center justify-center mb-5">
            <Film className="w-5 h-5 text-brass-400" strokeWidth={1.5} />
          </div>
          <h1 className="font-display text-2xl text-ink-100 tracking-marquee uppercase">Reel</h1>
          <p className="mt-2 text-xs text-ink-500 tracking-[0.2em] uppercase">Private Screening Room</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-stage-850/80 backdrop-blur border border-stage-700 rounded-2xl p-8 shadow-stage"
        >
          <div className="space-y-5">
            <div>
              <label htmlFor="username" className="block text-xs uppercase tracking-wider text-ink-500 mb-2">
                Username
              </label>
              <input
                id="username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full bg-stage-900 border border-stage-600 rounded-lg px-4 py-2.5 text-ink-100 placeholder:text-ink-500/60 outline-none focus:border-brass-400/70 transition-colors"
                placeholder="admin"
                required
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-xs uppercase tracking-wider text-ink-500 mb-2">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-stage-900 border border-stage-600 rounded-lg px-4 py-2.5 pr-11 text-ink-100 placeholder:text-ink-500/60 outline-none focus:border-brass-400/70 transition-colors"
                  placeholder="••••••••"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-500 hover:text-ink-300 transition-colors"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {error && (
              <div className="flex items-center gap-2 text-signal-red text-sm bg-signal-red/10 border border-signal-red/20 rounded-lg px-3 py-2.5">
                <Lock className="w-3.5 h-3.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full bg-brass-400 hover:bg-brass-300 disabled:opacity-60 disabled:hover:bg-brass-400 text-stage-950 font-medium rounded-lg py-2.5 transition-colors mt-2"
            >
              {submitting ? 'Verifying…' : 'Log In'}
            </button>
          </div>
        </form>

        <p className="text-center text-xs text-ink-500 mt-6">
          Prototype credentials — admin / 123
        </p>
      </div>
    </div>
  )
}
