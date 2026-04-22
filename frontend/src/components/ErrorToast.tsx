import { useCallback, useRef, useState } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faXmark, faTriangleExclamation } from '@fortawesome/free-solid-svg-icons'
import { ErrorContext } from './ErrorToastContext'
import './ErrorToast.css'

interface ToastEntry {
  id: number
  title: string
  detail: string
}

// ── Provider ──────────────────────────────────────────────────────────────────

const AUTO_DISMISS_MS = 6000

export function ErrorToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastEntry[]>([])
  const nextId = useRef(0)

  const dismiss = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  const pushError = useCallback((title: string, detail: string) => {
    const id = nextId.current++
    setToasts(prev => [...prev, { id, title, detail }])
    setTimeout(() => dismiss(id), AUTO_DISMISS_MS)
  }, [dismiss])

  return (
    <ErrorContext.Provider value={{ pushError }}>
      {children}
      <div className="toast-stack" aria-live="assertive">
        {toasts.map(t => (
          <div key={t.id} className="toast-card">
            <FontAwesomeIcon icon={faTriangleExclamation} className="toast-icon" />
            <div className="toast-body">
              <span className="toast-title">{t.title}</span>
              <span className="toast-detail">{t.detail}</span>
            </div>
            <button className="toast-close" onClick={() => dismiss(t.id)} aria-label="Dismiss">
              <FontAwesomeIcon icon={faXmark} />
            </button>
            <div className="toast-progress" style={{ animationDuration: `${AUTO_DISMISS_MS}ms` }} />
          </div>
        ))}
      </div>
    </ErrorContext.Provider>
  )
}
