import { useState, useEffect, useRef, useCallback } from 'react'
import logo from '../assets/logo.png'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCog, faMoon, faCircleInfo } from '@fortawesome/free-solid-svg-icons'
import { fetchInfo, InfoData } from '../api'
import { useErrorToast } from './ErrorToastContext'
import './HeaderBar.css'

export default function HeaderBar() {
  const { pushError } = useErrorToast()
  const [infoOpen, setInfoOpen] = useState(false)
  const [infoData, setInfoData] = useState<InfoData | null>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)

  const handleInfoClick = useCallback(async () => {
    if (!infoOpen && infoData === null) {
      try {
        const data = await fetchInfo()
        setInfoData(data)
      } catch (err: unknown) {
        pushError('Failed to load version info', String(err))
        return
      }
    }
    setInfoOpen(prev => !prev)
  }, [infoOpen, infoData, pushError])

  useEffect(() => {
    if (!infoOpen) return
    function handleMouseDown(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setInfoOpen(false)
      }
    }
    document.addEventListener('mousedown', handleMouseDown)
    return () => document.removeEventListener('mousedown', handleMouseDown)
  }, [infoOpen])

  return (
    <header className="header-bar">
      <img src={logo} alt="braindump" className="header-logo" />
      <div className="header-actions">
        <div className="info-btn-wrapper" ref={wrapperRef}>
          <button
            className="header-btn"
            aria-label="App info"
            title="App info"
            onClick={handleInfoClick}
          >
            <FontAwesomeIcon icon={faCircleInfo} />
          </button>
          {infoOpen && infoData && (
            <div className="info-panel">
              <div className="info-panel-row">
                <span className="info-panel-label">braindump</span>
                <span className="info-panel-value">v{infoData.version}</span>
              </div>
              <div className="info-panel-row">
                <span className="info-panel-label">wiki schema</span>
                <span className="info-panel-value">v{infoData.wiki_schema}</span>
              </div>
              <div className="info-panel-row">
                <span className="info-panel-label">meta</span>
                <span className="info-panel-value">v{infoData.meta}</span>
              </div>
              <div className="info-panel-row">
                <span className="info-panel-label">streams</span>
                <span className="info-panel-value">v{infoData.streams}</span>
              </div>
              <div className="info-panel-row">
                <span className="info-panel-label">dailies</span>
                <span className="info-panel-value">v{infoData.dailies}</span>
              </div>
            </div>
          )}
        </div>
        <button className="header-btn" disabled aria-label="Settings" title="Settings">
          <FontAwesomeIcon icon={faCog} />
        </button>
        <button className="header-btn" disabled aria-label="Toggle theme" title="Toggle theme">
          <FontAwesomeIcon icon={faMoon} />
        </button>
      </div>
    </header>
  )
}
