import logo from '../assets/logo.png'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCog, faMoon } from '@fortawesome/free-solid-svg-icons'
import './HeaderBar.css'

export default function HeaderBar() {
  return (
    <header className="header-bar">
      <img src={logo} alt="braindump" className="header-logo" />
      <div className="header-actions">
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
