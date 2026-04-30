import { useState, useMemo } from 'react'
import { Spike, Stream } from '../types'
import { formatDatetime, formatRelativeTime } from '../utils'
import './StreamsView.css'

interface Props {
  spikes: Spike[]
  streams: Stream[]
  summarizingStreams: Set<string>
  selectedId: string | null
  onSelect: (spike: Spike) => void
  onShowSummary: (streamName: string) => void
  onTriggerSummary: (streamName: string) => Promise<void>
}

interface Group {
  key: string
  label: string
  spikes: Spike[]
  maxModifiedAt: string
}

function buildStreamGroups(spikes: Spike[]): Group[] {
  const groupMap = new Map<string, Spike[]>()

  for (const spike of spikes) {
    const key = spike.stream ?? '__nostream__'
    if (!groupMap.has(key)) groupMap.set(key, [])
    groupMap.get(key)!.push(spike)
  }

  const groups: Group[] = []
  for (const [key, groupSpikes] of groupMap) {
    const sorted = [...groupSpikes].sort((a, b) => b.modifiedAt.localeCompare(a.modifiedAt))
    groups.push({
      key,
      label: key === '__nostream__' ? 'No stream' : key,
      spikes: sorted,
      maxModifiedAt: sorted[0]?.modifiedAt ?? '',
    })
  }

  groups.sort((a, b) => {
    if (a.key === '__nostream__') return 1
    if (b.key === '__nostream__') return -1
    return b.maxModifiedAt.localeCompare(a.maxModifiedAt)
  })

  return groups
}

// ── Spike row sub-component ──────────────────────────────────────────────────

interface SpikeRowProps {
  spike: Spike
  selected: boolean
  onSelect: (spike: Spike) => void
}

function SpikeRow({ spike, selected, onSelect }: SpikeRowProps) {
  return (
    <div
      className={`streams-spike-row${selected ? ' selected' : ''}`}
      onClick={() => onSelect(spike)}
      role="button"
      tabIndex={0}
      onKeyDown={(e: React.KeyboardEvent) => e.key === 'Enter' && onSelect(spike)}
      aria-label={spike.title}
    >
      <div className="streams-spike-title">{spike.title}</div>
      <div className="streams-spike-meta">
        <span className="spike-list-date">{formatDatetime(spike.modifiedAt)}</span>
        <span className="spike-list-tags">
          {spike.tags.map(t => <span key={t} className="tag">{t}</span>)}
        </span>
      </div>
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────

export default function StreamsView({
  spikes,
  streams,
  summarizingStreams,
  selectedId,
  onSelect,
  onShowSummary,
  onTriggerSummary,
}: Props) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  const toggleCollapsed = (key: string) => {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const groups = useMemo(() => buildStreamGroups(spikes), [spikes])

  const streamMap = useMemo(() => {
    const m = new Map<string, Stream>()
    for (const s of streams) m.set(s.name, s)
    return m
  }, [streams])

  return (
    <div className="streams-view">
      <div className="streams-body">
        {groups.length === 0 && (
          <div className="streams-empty">No spikes yet.</div>
        )}
        {groups.map(group => {
          const isNamed = group.key !== '__nostream__'
          const meta = isNamed ? streamMap.get(group.key) : undefined
          const hasSummary = !!meta?.summary_at
          const isPending = meta?.summary_pending ?? true
          const isGenerating = isNamed && summarizingStreams.has(group.key)
          const lastLabel = hasSummary
            ? `Last: ${formatRelativeTime(meta!.summary_at!)}`
            : 'Never'

          return (
            <div key={group.key} className="streams-group">
              <div
                className="streams-group-header"
                onClick={() => toggleCollapsed(group.key)}
                role="button"
                tabIndex={0}
                onKeyDown={(e: React.KeyboardEvent) => e.key === 'Enter' && toggleCollapsed(group.key)}
                aria-expanded={!collapsed.has(group.key)}
              >
                <span className={`streams-chevron${collapsed.has(group.key) ? ' collapsed' : ''}`}>▾</span>
                <div className="streams-group-title-area">
                  <span className="streams-group-name">{group.label}</span>

                {isNamed && (
                  <div className="streams-group-actions" onClick={(e: React.MouseEvent) => e.stopPropagation()}>
                    <button
                      className={`streams-action-btn streams-summarize-btn${isPending ? ' pending' : ''}${isGenerating ? ' loading' : ''}`}
                      disabled={isGenerating}
                      title={isPending ? 'New or edited spikes since last summary — click to summarize' : 'Regenerate summary'}
                      aria-label={`Summarize stream ${group.label}`}
                      onClick={() => void onTriggerSummary(group.key)}
                    >
                      ✦
                    </button>

                    {hasSummary && (
                      <button
                        className="streams-action-btn"
                        title="Show summary"
                        aria-label={`Show summary for ${group.label}`}
                        onClick={() => onShowSummary(group.key)}
                      >
                        ☰
                      </button>
                    )}

                    <span className="streams-summary-last">{lastLabel}</span>
                  </div>
                )}
                </div>
                <span className="streams-group-count">{group.spikes.length}</span>
              </div>

              {!collapsed.has(group.key) && (
                <div className="streams-group-items">
                  {group.spikes.map(spike => (
                    <SpikeRow
                      key={spike.id}
                      spike={spike}
                      selected={spike.id === selectedId}
                      onSelect={onSelect}
                    />
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
