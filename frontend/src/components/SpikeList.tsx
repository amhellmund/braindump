import { Spike } from '../types'
import { formatDatetime } from '../utils'
import './SpikeList.css'

interface Props {
  spikes: Spike[]
  selectedId: string | null
  onSelect: (spike: Spike) => void
}

export default function SpikeList({ spikes, selectedId, onSelect }: Props) {
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
