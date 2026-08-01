import { createContext, useContext, useEffect, useState } from 'react'
import { apiAuthStatus, apiLogin, apiLogout } from '../utils/api.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    let active = true

    const bootstrap = async () => {
      try {
        const result = await apiAuthStatus()
        if (!active) return
        setIsAuthenticated(Boolean(result.authenticated))
      } catch {
        if (!active) return
        setIsAuthenticated(false)
      } finally {
        if (active) setChecking(false)
      }
    }

    bootstrap()
    return () => {
      active = false
    }
  }, [])

  const login = async (username, password) => {
    try {
      const result = await apiLogin(username, password)
      setIsAuthenticated(true)
      return result
    } catch (error) {
      setIsAuthenticated(false)
      return { ok: false, error: error.message || 'Incorrect username or password.' }
    }
  }

  const logout = async () => {
    try {
      await apiLogout()
    } finally {
      setIsAuthenticated(false)
    }
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
