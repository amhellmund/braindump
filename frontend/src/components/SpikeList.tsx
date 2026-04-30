import { useState } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faRotate } from '@fortawesome/free-solid-svg-icons'
import { Spike } from '../types'
import { formatDatetime } from '../utils'
import './SpikeList.css'

interface Props {
  spikes: Spike[]
  selectedId: string | null
  onSelect: (spike: Spike) => void
  onUpdateWiki?: (id: string) => void
}

export default function SpikeList({ spikes, selectedId, onSelect, onUpdateWiki }: Props) {
  const [triggered, setTriggered] = useState<Set<string>>(new Set())

  return (
    <div className="spike-list">
      <div className="spike-list-header">Recent spikes</div>
      {spikes.length === 0 && (
        <div className="spike-list-empty">No spikes yet.</div>
      )}
      {spikes.map(spike => (
        <div
          key={spike.id}
          className={`spike-list-item ${spike.id === selectedId ? 'selected' : ''}`}
          onClick={() => onSelect(spike)}
        >
          {spike.wikiPending && (
            <button
              className="spike-list-pending-btn"
              title="Update wiki"
              aria-label="Update wiki for this spike"
              disabled={triggered.has(spike.id)}
              onClick={(e: React.MouseEvent) => {
                e.stopPropagation()
                setTriggered(prev => new Set(prev).add(spike.id))
                onUpdateWiki?.(spike.id)
              }}
            >
              <FontAwesomeIcon icon={faRotate} />
            </button>
          )}
          <div className="spike-list-title">
            <span>{spike.title}</span>
          </div>
          <div className="spike-list-meta">
            <span className="spike-list-date">{formatDatetime(spike.modifiedAt)}</span>
            <span className="spike-list-tags">
              {spike.tags.map(t => (
                <span key={t} className="tag">{t}</span>
              ))}
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}
