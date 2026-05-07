import { createContext, useContext, useState, useEffect } from 'react'
import { fetchWhoAmI, fetchLogout } from './api'

interface AuthState {
  username: string | null
  sessionChecked: boolean
  setAuth: (username: string) => void
  clearAuth: () => Promise<void>
}

const AuthContext = createContext<AuthState>({
  username: null,
  sessionChecked: false,
  setAuth: () => {},
  clearAuth: async () => {},
})

export function useAuth() {
  return useContext(AuthContext)
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [username, setUsername] = useState<string | null>(null)
  const [sessionChecked, setSessionChecked] = useState(false)

  useEffect(() => {
    fetchWhoAmI()
      .then(data => setUsername(data.username))
      .catch(() => setUsername(null))
      .finally(() => setSessionChecked(true))
  }, []) // runs once on mount to restore session from HttpOnly cookie

  const setAuth = (newUsername: string) => {
    setUsername(newUsername)
  }

  const clearAuth = async () => {
    try { await fetchLogout() } catch { /* best-effort */ }
    setUsername(null)
  }

  return (
    <AuthContext.Provider value={{ username, sessionChecked, setAuth, clearAuth }}>
      {children}
    </AuthContext.Provider>
  )
}
