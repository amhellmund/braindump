import { useState, useCallback, useEffect, useRef } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCircleCheck, faArrowsRotate } from '@fortawesome/free-solid-svg-icons'
import {
  fetchLog,
  LogEntry,
  LogDetail,
  WikiUpdateLogDetail,
  WikiRemoveLogDetail,
  HealthCheckLogDetail,
  HealthRepairLogDetail,
  StreamSummaryLogDetail,
  DailySummaryLogDetail,
} from '../api'
import './StatusBar.css'

interface StatusBarProps {
  syncing: boolean
  healthCheck: boolean
  isSummarizing: boolean
  totalCostUsd: number
  totalTokens: number
  syncCount: number
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

function formatCost(usd: number): string {
  if (usd === 0) return '$0.000'
  if (usd < 0.001) return '<$0.001'
  return '$' + usd.toFixed(3)
}

function formatChars(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ts
  }
}

function WikiUpdateDetail({ d }: { d: WikiUpdateLogDetail }) {
  return (
    <>
      {d.index_section && (
        <div className="status-log-detail-section">
          <div className="status-log-detail-label">Index entry</div>
          <pre className="status-log-detail-pre">{d.index_section}</pre>
        </div>
      )}
      <div className="status-log-detail-section">
        <div className="status-log-detail-label">Connections</div>
        {d.connections_lines.length > 0
          ? <pre className="status-log-detail-pre">{d.connections_lines.join('\n')}</pre>
          : <span className="status-log-detail-none">None</span>
        }
      </div>
      {d.hierarchy_section && (
        <div className="status-log-detail-section">
          <div className="status-log-detail-label">Hierarchy</div>
          <pre className="status-log-detail-pre">{d.hierarchy_section}</pre>
        </div>
      )}
      <div className="status-log-detail-meta">
        {formatTokens(d.total_tokens)} tokens · {formatCost(d.cost_usd)}
        {' · '}system: {d.system_prompt_chars != null ? formatChars(d.system_prompt_chars) + ' chars' : 'n/a'}
        {' · '}prompt: {d.prompt_chars != null ? formatChars(d.prompt_chars) + ' chars' : 'n/a'}
      </div>
    </>
  )
}

function WikiRemoveDetail({ d }: { d: WikiRemoveLogDetail }) {
  return (
    <>
      <div className="status-log-detail-section">
        <div className="status-log-detail-label">Spike ID</div>
        <span className="status-log-detail-value">{d.spike_id}</span>
      </div>
      <div className="status-log-detail-meta">
        {formatTokens(d.total_tokens)} tokens · {formatCost(d.cost_usd)}
        {' · '}system: {d.system_prompt_chars != null ? formatChars(d.system_prompt_chars) + ' chars' : 'n/a'}
        {' · '}prompt: {d.prompt_chars != null ? formatChars(d.prompt_chars) + ' chars' : 'n/a'}
      </div>
    </>
  )
}

function HealthCheckDetail({ d }: { d: HealthCheckLogDetail }) {
  return (
    <div className="status-log-detail-section">
      <div className="status-log-detail-label">Issues</div>
      {d.issues.length === 0
        ? <span className="status-log-detail-none">No issues found</span>
        : (
          <ul className="status-log-detail-list">
            {d.issues.map((issue, i) => <li key={i}>{issue}</li>)}
          </ul>
        )
      }
    </div>
  )
}

function HealthRepairDetail({ d }: { d: HealthRepairLogDetail }) {
  return (
    <>
      <div className="status-log-detail-section">
        <div className="status-log-detail-label">Repaired</div>
        <span className="status-log-detail-value">{d.repaired_count} spike(s)</span>
      </div>
      {d.errors.length > 0 && (
        <div className="status-log-detail-section">
          <div className="status-log-detail-label">Errors</div>
          <ul className="status-log-detail-list status-log-detail-errors">
            {d.errors.map((err, i) => <li key={i}>{err}</li>)}
          </ul>
        </div>
      )}
    </>
  )
}

function StreamSummaryDetail({ d }: { d: StreamSummaryLogDetail }) {
  return (
    <div className="status-log-detail-meta">
      {formatTokens(d.total_tokens)} tokens · {formatCost(d.cost_usd)} · {d.spike_count} spike(s)
    </div>
  )
}

function DailySummaryDetail({ d }: { d: DailySummaryLogDetail }) {
  return (
    <div className="status-log-detail-meta">
      {formatTokens(d.total_tokens)} tokens · {formatCost(d.cost_usd)} · {d.spike_count} spike(s)
    </div>
  )
}

function LogEntryDetail({ detail }: { detail: LogDetail }) {
  switch (detail.kind) {
    case 'wiki_update':    return <WikiUpdateDetail d={detail} />
    case 'wiki_remove':    return <WikiRemoveDetail d={detail} />
    case 'health_check':   return <HealthCheckDetail d={detail} />
    case 'health_repair':  return <HealthRepairDetail d={detail} />
    case 'stream_summary': return <StreamSummaryDetail d={detail} />
    case 'daily_summary':  return <DailySummaryDetail d={detail} />
  }
}

type LogTab = 'spike' | 'health'

function classifyEntry(entry: LogEntry): LogTab {
  if (entry.detail) {
    return entry.detail.kind === 'health_check' || entry.detail.kind === 'health_repair'
      ? 'health'
      : 'spike'
  }
  return entry.summary.toLowerCase().startsWith('health') ? 'health' : 'spike'
}

export default function StatusBar({ syncing, healthCheck, isSummarizing, totalCostUsd, totalTokens, syncCount }: StatusBarProps) {
  const [showLog, setShowLog] = useState(false)
  const [logEntries, setLogEntries] = useState<LogEntry[]>([])
  const [logLoading, setLogLoading] = useState(false)
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null)
  const [activeTab, setActiveTab] = useState<LogTab>('spike')
  const barRef = useRef<HTMLDivElement>(null)
  const [overlayBottom, setOverlayBottom] = useState(0)

  useEffect(() => {
    if (!showLog) return
    setLogLoading(true)
    fetchLog(100)
      .then(data => setLogEntries(data.entries))
      .catch(() => setLogEntries([{ ts: '', summary: 'Failed to load log.' }]))
      .finally(() => setLogLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [syncCount]) // intentionally omits showLog: only refresh on new sync events, not on open

  const openLog = useCallback(() => {
    if (barRef.current) {
      const rect = barRef.current.getBoundingClientRect()
      setOverlayBottom(window.innerHeight - rect.top + 4)
    }
    setShowLog(true)
    setExpandedIndex(null)
    setActiveTab('spike')
    setLogLoading(true)
    fetchLog(100)
      .then(data => setLogEntries(data.entries))
      .catch(() => setLogEntries([{ ts: '', summary: 'Failed to load log.' }]))
      .finally(() => setLogLoading(false))
  }, [])

  const closeLog = useCallback(() => setShowLog(false), [])

  const switchTab = useCallback((tab: LogTab) => {
    setActiveTab(tab)
    setExpandedIndex(null)
  }, [])

  const toggleEntry = useCallback((i: number) => {
    setExpandedIndex(prev => prev === i ? null : i)
  }, [])

  const visibleEntries = logEntries.filter(e => classifyEntry(e) === activeTab)

  return (
    <div className="status-bar" ref={barRef}>
      {showLog && (
        <div className="status-log-overlay" style={{ bottom: overlayBottom }}>
          <div className="status-log-header">
            <div className="status-log-tabs" role="tablist">
              <button
                className={`status-log-tab${activeTab === 'spike' ? ' active' : ''}`}
                role="tab"
                aria-selected={activeTab === 'spike'}
                onClick={() => switchTab('spike')}
              >
                Spike Updates
              </button>
              <button
                className={`status-log-tab${activeTab === 'health' ? ' active' : ''}`}
                role="tab"
                aria-selected={activeTab === 'health'}
                onClick={() => switchTab('health')}
              >
                Health Checks
              </button>
            </div>
            <button className="status-log-close" onClick={closeLog} aria-label="Close log">✕</button>
          </div>
          <div className="status-log-body">
            {logLoading && <span className="status-log-loading">Loading…</span>}
            {!logLoading && visibleEntries.length === 0 && (
              <span className="status-log-empty">
                {activeTab === 'spike' ? 'No spike updates yet.' : 'No health checks yet.'}
              </span>
            )}
            {!logLoading && visibleEntries.map((entry, i) => {
              const hasDetail = Boolean(entry.detail)
              const expanded = expandedIndex === i
              return (
                <div key={i} className="status-log-entry">
                  <div
                    className={`status-log-entry-header${hasDetail ? ' expandable' : ''}`}
                    onClick={hasDetail ? () => toggleEntry(i) : undefined}
                  >
                    <span className="status-log-entry-ts">{entry.ts ? formatTs(entry.ts) : ''}</span>
                    <span className="status-log-entry-summary">{entry.summary}</span>
                    {hasDetail && (
                      <span className="status-log-entry-chevron" aria-hidden={true}>
                        {expanded ? '▲' : '▼'}
                      </span>
                    )}
                  </div>
                  {expanded && entry.detail && (
                    <div className="status-log-entry-detail">
                      <LogEntryDetail detail={entry.detail} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      <button
        className={`status-pill${(syncing || isSummarizing) ? ' syncing' : ''}`}
        onClick={showLog ? closeLog : openLog}
        aria-label={syncing ? (healthCheck ? 'Health check running — click to view log' : 'LLM updating — click to view log') : isSummarizing ? 'Summarizing stream — click to view log' : 'Synced — click to view log'}
      >
        <FontAwesomeIcon
          icon={(syncing || isSummarizing) ? faArrowsRotate : faCircleCheck}
          className="status-icon"
          spin={syncing || isSummarizing}
          aria-hidden={true}
        />
        {syncing ? (healthCheck ? 'Health check' : 'Updating') : isSummarizing ? 'Summarizing' : 'Synced'}
      </button>

      <div className="status-usage">
        <span className="status-usage-tokens" title="Total tokens used since server start">
          {formatTokens(totalTokens)} tokens
        </span>
        <span className="status-usage-divider" aria-hidden="true" />
        <span className="status-usage-cost" title="Estimated cost since server start">
          {formatCost(totalCostUsd)}
        </span>
      </div>
    </div>
  )
}
