import { useState, useMemo } from 'react'
import { Spike, Daily } from '../types'
import { formatDatetime, formatRelativeTime } from '../utils'
import './DailiesView.css'

interface Props {
  spikes: Spike[]
  dailies: Daily[]
  summarizingDailies: Set<string>
  selectedId: string | null
  onSelect: (spike: Spike) => void
  onShowSummary: (date: string) => void
  onTriggerSummary: (date: string) => Promise<void>
}

interface Group {
  date: string
  spikes: Spike[]
}

function buildDailyGroups(spikes: Spike[]): Group[] {
  const groupMap = new Map<string, Spike[]>()

  for (const spike of spikes) {
    const date = spike.createdAt.slice(0, 10)
    if (!groupMap.has(date)) groupMap.set(date, [])
    groupMap.get(date)!.push(spike)
  }

  const groups: Group[] = []
  for (const [date, groupSpikes] of groupMap) {
    const sorted = [...groupSpikes].sort((a, b) => b.modifiedAt.localeCompare(a.modifiedAt))
    groups.push({ date, spikes: sorted })
  }

  groups.sort((a, b) => b.date.localeCompare(a.date))
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
      className={`dailies-spike-row${selected ? ' selected' : ''}`}
      onClick={() => onSelect(spike)}
      role="button"
      tabIndex={0}
      onKeyDown={(e: React.KeyboardEvent) => e.key === 'Enter' && onSelect(spike)}
      aria-label={spike.title}
    >
      <div className="dailies-spike-title">{spike.title}</div>
      <div className="dailies-spike-meta">
        <span className="spike-list-date">{formatDatetime(spike.modifiedAt)}</span>
        <span className="spike-list-tags">
          {spike.tags.map(t => <span key={t} className="tag">{t}</span>)}
        </span>
      </div>
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────

export default function DailiesView({
  spikes,
  dailies,
  summarizingDailies,
  selectedId,
  onSelect,
  onShowSummary,
  onTriggerSummary,
}: Props) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  const toggleCollapsed = (date: string) => {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(date)) next.delete(date)
      else next.add(date)
      return next
    })
  }

  const groups = useMemo(() => buildDailyGroups(spikes), [spikes])

  const dailyMap = useMemo(() => {
    const m = new Map<string, Daily>()
    for (const d of dailies) m.set(d.date, d)
    return m
  }, [dailies])

  return (
    <div className="dailies-view">
      <div className="dailies-body">
        {groups.length === 0 && (
          <div className="dailies-empty">No spikes yet.</div>
        )}
        {groups.map(group => {
          const meta = dailyMap.get(group.date)
          const hasSummary = !!meta?.summary_at
          const isPending = meta?.summary_pending ?? true
          const isGenerating = summarizingDailies.has(group.date)
          const lastLabel = hasSummary
            ? `Last: ${formatRelativeTime(meta!.summary_at!)}`
            : 'Never'

          return (
            <div key={group.date} className="dailies-group">
              <div
                className="dailies-group-header"
                onClick={() => toggleCollapsed(group.date)}
                role="button"
                tabIndex={0}
                onKeyDown={(e: React.KeyboardEvent) => e.key === 'Enter' && toggleCollapsed(group.date)}
                aria-expanded={!collapsed.has(group.date)}
              >
                <span className={`dailies-chevron${collapsed.has(group.date) ? ' collapsed' : ''}`}>▾</span>
                <div className="dailies-group-title-area">
                  <span className="dailies-group-name">{group.date}</span>

                <div className="dailies-group-actions" onClick={(e: React.MouseEvent) => e.stopPropagation()}>
                  <button
                    className={`dailies-action-btn dailies-summarize-btn${isPending ? ' pending' : ''}${isGenerating ? ' loading' : ''}`}
                    disabled={isGenerating}
                    title={isPending ? 'New or edited spikes since last summary — click to summarize' : 'Regenerate summary'}
                    aria-label={`Summarize day ${group.date}`}
                    onClick={() => void onTriggerSummary(group.date)}
                  >
                    ✦
                  </button>

                  {hasSummary && (
                    <button
                      className="dailies-action-btn"
                      title="Show summary"
                      aria-label={`Show summary for ${group.date}`}
                      onClick={() => onShowSummary(group.date)}
                    >
                      ☰
                    </button>
                  )}

                  <span className="dailies-summary-last">{lastLabel}</span>
                </div>
                </div>
                <span className="dailies-group-count">{group.spikes.length}</span>
              </div>

              {!collapsed.has(group.date) && (
                <div className="dailies-group-items">
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
