import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faPlus, faBolt, faCalendarDay, faLayerGroup } from '@fortawesome/free-solid-svg-icons'
import { IconDefinition } from '@fortawesome/fontawesome-svg-core'
import './NavBar.css'

export type NavView = 'spikes' | 'dailies' | 'streams'

interface Props {
  activeView: NavView
  onAddSpike: () => void
  onViewChange: (view: NavView) => void
}

interface NavItem {
  id: NavView
  icon: IconDefinition
  caption: string
  disabled: boolean
}

const NAV_ITEMS: NavItem[] = [
  { id: 'spikes',  icon: faBolt,        caption: 'Spikes',   disabled: false },
  { id: 'dailies', icon: faCalendarDay, caption: 'Dailies',  disabled: true  },
  { id: 'streams', icon: faLayerGroup,  caption: 'Streams',  disabled: false },
]

export default function NavBar({ activeView, onAddSpike, onViewChange }: Props) {
  return (
    <nav className="nav-bar">
      <button
        className="nav-btn nav-btn-primary"
        onClick={onAddSpike}
        aria-label="Add spike"
        title="Add spike"
      >
        <FontAwesomeIcon icon={faPlus} className="nav-btn-icon" />
      </button>

      {NAV_ITEMS.map(item => (
        <button
          key={item.id}
          className={`nav-btn${activeView === item.id ? ' active' : ''}`}
          onClick={() => onViewChange(item.id)}
          disabled={item.disabled}
          aria-label={item.caption}
          title={item.caption}
        >
          <FontAwesomeIcon icon={item.icon} className="nav-btn-icon" />
          <span className="nav-btn-caption">{item.caption}</span>
        </button>
      ))}
    </nav>
  )
}
