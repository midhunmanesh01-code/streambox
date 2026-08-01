import { createContext, useContext, useEffect, useState } from 'react'

const AuthContext = createContext(null)

const SESSION_KEY = 'reel_session'

// TEMPORARY frontend-only credential check.
// Replace `mockLogin` with a real call to POST /api/auth/login when the
// Flask backend is ready. Keep the same function signature so nothing
// else in the app has to change.
async function mockLogin(username, password) {
  await new Promise((resolve) => setTimeout(resolve, 500))
  if (username === 'admin' && password === '123') {
    return { ok: true, token: 'mock-session-token' }
  }
  return { ok: false, error: 'Incorrect username or password.' }
}

export function AuthProvider({ children }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    const existing = sessionStorage.getItem(SESSION_KEY)
    setIsAuthenticated(existing === 'mock-session-token')
    setChecking(false)
  }, [])

  const login = async (username, password) => {
    const result = await mockLogin(username, password)
    if (result.ok) {
      sessionStorage.setItem(SESSION_KEY, result.token)
      setIsAuthenticated(true)
    }
    return result
  }

  const logout = () => {
    sessionStorage.removeItem(SESSION_KEY)
    setIsAuthenticated(false)
  }

  return (
    <AuthContext.Provider value={{ isAuthenticated, checking, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
