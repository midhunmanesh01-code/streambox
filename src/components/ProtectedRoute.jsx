import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

export default function ProtectedRoute({ children }) {
  const { isAuthenticated, checking } = useAuth()

  if (checking) {
    return (
      <div className="min-h-screen bg-stage-950 flex items-center justify-center">
        <div className="w-8 h-8 rounded-full border-2 border-stage-600 border-t-brass-400 animate-spin" />
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return children
}
