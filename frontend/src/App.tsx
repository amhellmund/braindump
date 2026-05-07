import { useState, useMemo, useRef, useCallback, useEffect } from 'react'
import { Daily, Spike, Stream } from './types'
import {
  fetchSpikes,
  fetchGraph,
  fetchStatus,
  createSpike,
  updateSpike,
  updateSpikeWiki,
  triggerPendingWikiUpdates,
  triggerWikiRepair,
  deleteSpike,
  fetchStreams,
  fetchStreamSummary,
  triggerStreamSummary,
  fetchDailies,
  fetchDailySummary,
  triggerDailySummary,
  fetchAuthMode,
  ConflictError,
  GraphData,
} from './api'
import SearchBar from './components/SearchBar'
import SpikeList from './components/SpikeList'
import SpikeEditor from './components/SpikeEditor'
import SpikeDetail from './components/SpikeDetail'
import GraphView from './components/GraphView'
import HierarchyView from './components/HierarchyView'
import QueryBar from './components/QueryBar'
import StatusBar from './components/StatusBar'
import NavBar, { NavView } from './components/NavBar'
import StreamsView from './components/StreamsView'
import StreamSummaryPanel from './components/StreamSummaryPanel'
import DailiesView from './components/DailiesView'
import HeaderBar from './components/HeaderBar'
import LoginPage from './components/LoginPage'
import { ErrorToastProvider } from './components/ErrorToast'
import { useErrorToast } from './components/ErrorToastContext'
import { AuthProvider, useAuth } from './auth'
import './App.css'

type RightPanel = { mode: 'editor'; spike: Spike | null }
                | { mode: 'detail'; spike: Spike; highlightSection: string | null }
                | { mode: 'stream-summary'; streamName: string; content: string; generatedAt: string }
                | { mode: 'daily-summary'; date: string; content: string; generatedAt: string }
                | null

export default function App() {
  return (
    <AuthProvider>
      <ErrorToastProvider>
        <AuthGate />
      </ErrorToastProvider>
    </AuthProvider>
  )
}

function AuthGate() {
  const { username, sessionChecked, clearAuth } = useAuth()
  const [multiUser, setMultiUser] = useState<boolean | null>(null)

  // Listen for 401 events dispatched by api.ts.
  useEffect(() => {
    const handler = () => { clearAuth().catch(() => {}) }
    window.addEventListener('braindump-unauthorized', handler)
    return () => window.removeEventListener('braindump-unauthorized', handler)
  }, [clearAuth])

  // Detect single-user vs multi-user mode on mount.
  useEffect(() => {
    fetchAuthMode().then(mode => setMultiUser(mode.multi_user)).catch(() => setMultiUser(false))
  }, [])

  // Wait for both the auth-mode probe and the whoami probe to complete.
  if (multiUser === null || !sessionChecked) return null

  // Single-user mode: skip login entirely.
  if (!multiUser) return <AppInner multiUser={false} />

  // Multi-user: require an active session.
  if (!username) return <LoginPage onLogin={() => {}} />

  return <AppInner multiUser={true} />
}

function AppInner({ multiUser }: { multiUser: boolean }) {
  const { pushError } = useErrorToast()
  const [spikes, setSpikes] = useState<Spike[]>([])
  const [search, setSearch] = useState('')
  const [selectedSpikeId, setSelectedSpikeId] = useState<string | null>(null)
  const [selectedSectionHeading, setSelectedSectionHeading] = useState<string | null>(null)
  const [rightPanel, setRightPanel] = useState<RightPanel>(null)
  const [zoomLevel, setZoomLevel] = useState<0 | 1 | 2>(2)
  const [rightPanelWidth, setRightPanelWidth] = useState<number>(() => {
    const stored = localStorage.getItem('braindump-right-panel-width')
    const parsed = stored ? parseFloat(stored) : NaN
    return isNaN(parsed) ? 20 : Math.min(50, Math.max(20, parsed))
  })
  const isDragging = useRef(false)
  const [isResizing, setIsResizing] = useState(false)
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], edges: [] })
  const [activeNav, setActiveNav] = useState<NavView>('spikes')
  const [mainView, setMainView] = useState<'graph' | 'hierarchy'>('hierarchy')
  const [hierarchyGroupMode, setHierarchyGroupMode] = useState<'community' | 'tag'>('community')
  const [hierarchyData, setHierarchyData] = useState<GraphData | null>(null)
  const [hierarchyLoading, setHierarchyLoading] = useState(true)
  const [isSyncing, setIsSyncing] = useState(false)
  const [isHealthCheck, setIsHealthCheck] = useState(false)
  const [totalCostUsd, setTotalCostUsd] = useState(0)
  const [totalTokens, setTotalTokens] = useState(0)
  const [syncCount, setSyncCount] = useState(0)
  const [streams, setStreams] = useState<Stream[]>([])
  const [summarizingStreams, setSummarizingStreams] = useState<Set<string>>(new Set())
  const [dailies, setDailies] = useState<Daily[]>([])
  const [summarizingDailies, setSummarizingDailies] = useState<Set<string>>(new Set())

  useEffect(() => {
    fetchSpikes()
      .then(setSpikes)
      .catch((err: unknown) => pushError('Failed to load spikes', String(err)))
    fetchStreams()
      .then(setStreams)
      .catch(() => {})
    fetchDailies()
      .then(setDailies)
      .catch(() => {})
    fetchStatus()
      .then(s => {
        setIsSyncing(s.syncing)
        setTotalCostUsd(s.total_cost_usd)
        setTotalTokens(s.total_tokens)
      })
      .catch(() => {})
    fetchGraph(1)
      .then(data => { setHierarchyData(data); setHierarchyLoading(false) })
      .catch((err: unknown) => {
        pushError('Failed to load communities', String(err))
        setHierarchyLoading(false)
      })
  }, [pushError])

  const loadGraph = useCallback(() => {
    fetchGraph(zoomLevel)
      .then(setGraphData)
      .catch((err: unknown) => pushError('Failed to load graph', String(err)))
  }, [zoomLevel, pushError])

  useEffect(() => { loadGraph() }, [loadGraph])

  // Always keep a ref to the latest loadGraph so the WebSocket handler
  // (registered once) never calls a stale closure.
  const loadGraphRef = useRef(loadGraph)
  useEffect(() => { loadGraphRef.current = loadGraph }, [loadGraph])

  // Ref so the WebSocket handler can read whether hierarchy data is cached.
  const hierarchyDataRef = useRef(hierarchyData)
  useEffect(() => { hierarchyDataRef.current = hierarchyData }, [hierarchyData])

  useEffect(() => {
    let destroyed = false
    let ws: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let backoffMs = 1000

    const connect = () => {
      if (destroyed) return
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${proto}//${window.location.host}/api/v1/ws`
      ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        backoffMs = 1000  // reset backoff after a successful connection
      }

      ws.onmessage = (event: MessageEvent) => {
        try {
          const msg = JSON.parse(event.data as string) as {
            type: string
            spike_id?: string | null
            stream_name?: string
            date?: string
            syncing?: boolean
            health_check?: boolean
            total_cost_usd?: number
            total_tokens?: number
            error?: string
          }
          if (msg.type === 'ping') {
            // server keepalive — no action needed
          } else if (msg.type === 'sync_start') {
            setIsSyncing(true)
            if (msg.health_check) setIsHealthCheck(true)
          } else if (msg.type === 'sync_error') {
            pushError('Wiki sync failed', msg.error ?? 'Unknown error')
          } else if (msg.type === 'sync_done') {
            const stillSyncing = msg.syncing ?? false
            setIsSyncing(stillSyncing)
            if (!stillSyncing) setIsHealthCheck(false)
            if (msg.total_cost_usd !== undefined) setTotalCostUsd(msg.total_cost_usd)
            if (msg.total_tokens !== undefined) setTotalTokens(msg.total_tokens)
            loadGraphRef.current()
            fetchSpikes().then(setSpikes).catch(() => {})
            setSyncCount(c => c + 1)
            // Silently refresh hierarchy community data if it has been loaded.
            if (hierarchyDataRef.current !== null) {
              fetchGraph(1).then(setHierarchyData).catch(() => {})
            }
          } else if (msg.type === 'usage_update') {
            if (msg.total_cost_usd !== undefined) setTotalCostUsd(msg.total_cost_usd)
            if (msg.total_tokens !== undefined) setTotalTokens(msg.total_tokens)
          } else if (msg.type === 'stream_summary_start' && msg.stream_name) {
            setSummarizingStreams(prev => new Set(prev).add(msg.stream_name!))
          } else if (msg.type === 'stream_summary_done' && msg.stream_name) {
            setSummarizingStreams(prev => {
              const next = new Set(prev)
              next.delete(msg.stream_name!)
              return next
            })
            fetchStreams().then(setStreams).catch(() => {})
          } else if (msg.type === 'daily_summary_start' && msg.date) {
            setSummarizingDailies(prev => new Set(prev).add(msg.date!))
          } else if (msg.type === 'daily_summary_done' && msg.date) {
            setSummarizingDailies(prev => {
              const next = new Set(prev)
              next.delete(msg.date!)
              return next
            })
            fetchDailies().then(setDailies).catch(() => {})
          }
        } catch {
          // ignore malformed messages
        }
      }

      ws.onerror = () => {
        // onclose fires immediately after onerror, reconnect logic lives there
        ws?.close()
      }

      ws.onclose = () => {
        if (destroyed) return
        reconnectTimer = setTimeout(() => {
          backoffMs = Math.min(backoffMs * 2, 30_000)
          connect()
        }, backoffMs)
      }
    }

    connect()

    return () => {
      destroyed = true
      if (reconnectTimer !== null) clearTimeout(reconnectTimer)
      ws?.close()
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps -- refs are stable; setters are stable

  const handleSwitchToHierarchy = useCallback(() => {
    setMainView('hierarchy')
    // Lazy-load zoom=1 community data on first switch; cache thereafter.
    if (hierarchyDataRef.current === null) {
      setHierarchyLoading(true)
      fetchGraph(1)
        .then(data => { setHierarchyData(data); setHierarchyLoading(false) })
        .catch((err: unknown) => {
          pushError('Failed to load communities', String(err))
          setHierarchyLoading(false)
        })
    }
  }, [pushError])

  // All unique tags across the corpus — for TagsInput suggestions
  const allTags = useMemo(() =>
    [...new Set(spikes.flatMap(s => s.tags))].sort(),
    [spikes]
  )

  // All unique stream names sorted by most-recent activity first (max spike modifiedAt per stream)
  const allStreams = useMemo(() => {
    const lastActivity = new Map<string, string>()
    for (const spike of spikes) {
      if (!spike.stream) continue
      const prev = lastActivity.get(spike.stream) ?? ''
      if (spike.modifiedAt > prev) lastActivity.set(spike.stream, spike.modifiedAt)
    }
    return [...lastActivity.keys()].sort(
      (a, b) => (lastActivity.get(b) ?? '').localeCompare(lastActivity.get(a) ?? '')
    )
  }, [spikes])

  const pendingCount = useMemo(() => spikes.filter(s => s.wikiPending).length, [spikes])

  // Filtered spike list (sidebar)
  const filteredSpikes = useMemo(() => {
    const q = search.toLowerCase()
    if (!q) return spikes
    return spikes.filter(s =>
      s.title.toLowerCase().includes(q) ||
      s.tags.some(t => t.includes(q)) ||
      s.raw.toLowerCase().includes(q)
    )
  }, [spikes, search])

  const handleSpikeSelect = (spike: Spike) => {
    setSelectedSpikeId(spike.id)
    setSelectedSectionHeading(null)
    setRightPanel({ mode: 'detail', spike, highlightSection: null })
  }

  const handleNodeClick = ({ spikeId, sectionHeading }: { spikeId: string; sectionHeading: string | null }) => {
    const spike = spikes.find(s => s.id === spikeId)
    if (!spike) return
    setSelectedSpikeId(spikeId)
    setSelectedSectionHeading(sectionHeading)
    setRightPanel({ mode: 'detail', spike, highlightSection: sectionHeading })
  }

  const handleDelete = async (spikeId: string) => {
    try {
      await deleteSpike(spikeId)
      setSpikes(prev => prev.filter(s => s.id !== spikeId))
      setSelectedSpikeId(null)
      setRightPanel(null)
    } catch (err: unknown) {
      pushError('Failed to delete spike', String(err))
    }
  }

  // Save a spike — receives body (no frontmatter), tags, stream, updateWiki, and optimistic lock value
  const handleSave = async (
    body: string,
    tags: string[],
    stream: string | null,
    updateWiki: boolean,
    expectedModifiedAt: string | null,
  ) => {
    const editingSpike = rightPanel?.mode === 'editor' ? rightPanel.spike : null
    const raw = `---\ntags: [${tags.join(', ')}]\n---\n\n${body}`

    try {
      if (editingSpike) {
        const updated = await updateSpike(editingSpike.id, raw, stream, updateWiki, expectedModifiedAt)
        setSpikes(prev => prev.map(s => s.id === editingSpike.id ? updated : s))
        setRightPanel({ mode: 'detail', spike: updated, highlightSection: null })
      } else {
        const newSpike = await createSpike(raw, stream, updateWiki)
        setSpikes(prev => [newSpike, ...prev])
        setSelectedSpikeId(newSpike.id)
        setRightPanel({ mode: 'detail', spike: newSpike, highlightSection: null })
      }
      fetchStreams().then(setStreams).catch(() => {})
    } catch (err: unknown) {
      // ConflictError is surfaced by SpikeEditor itself; re-throw for the editor to handle.
      if (err instanceof ConflictError) throw err
      pushError('Failed to save spike', String(err))
    }
  }

  const handleUpdateWiki = async (spikeId: string) => {
    try {
      await updateSpikeWiki(spikeId)
    } catch (err: unknown) {
      pushError('Failed to queue wiki update', String(err))
    }
  }

  const handleUpdatePending = async () => {
    try {
      await triggerPendingWikiUpdates()
    } catch (err: unknown) {
      pushError('Failed to queue pending wiki updates', String(err))
    }
  }

  const handleRepair = async () => {
    try {
      await triggerWikiRepair()
    } catch (err: unknown) {
      pushError('Failed to trigger wiki repair', String(err))
    }
  }

  const handleShowSummary = useCallback(async (streamName: string) => {
    try {
      const resp = await fetchStreamSummary(streamName)
      setRightPanel({ mode: 'stream-summary', streamName, content: resp.content, generatedAt: resp.generated_at })
    } catch (err: unknown) {
      pushError('Failed to load stream summary', String(err))
    }
  }, [pushError])

  const handleTriggerSummary = useCallback(async (streamName: string) => {
    setSummarizingStreams(prev => new Set(prev).add(streamName))
    try {
      await triggerStreamSummary(streamName)
    } catch (err: unknown) {
      setSummarizingStreams(prev => { const next = new Set(prev); next.delete(streamName); return next })
      pushError('Failed to start stream summarization', String(err))
    }
  }, [pushError])

  const handleShowDailySummary = useCallback(async (date: string) => {
    try {
      const resp = await fetchDailySummary(date)
      setRightPanel({ mode: 'daily-summary', date, content: resp.content, generatedAt: resp.generated_at })
    } catch (err: unknown) {
      pushError('Failed to load daily summary', String(err))
    }
  }, [pushError])

  const handleTriggerDailySummary = useCallback(async (date: string) => {
    setSummarizingDailies(prev => new Set(prev).add(date))
    try {
      await triggerDailySummary(date)
    } catch (err: unknown) {
      setSummarizingDailies(prev => { const next = new Set(prev); next.delete(date); return next })
      pushError('Failed to start daily summarization', String(err))
    }
  }, [pushError])

  const handleResizeMouseDown = (e: React.MouseEvent) => {
    e.preventDefault()
    isDragging.current = true
    setIsResizing(true)

    const onMouseMove = (ev: MouseEvent) => {
      if (!isDragging.current) return
      const pct = ((window.innerWidth - ev.clientX) / window.innerWidth) * 100
      setRightPanelWidth(Math.min(50, Math.max(20, pct)))
    }

    const onMouseUp = (ev: MouseEvent) => {
      isDragging.current = false
      setIsResizing(false)
      const pct = ((window.innerWidth - ev.clientX) / window.innerWidth) * 100
      const clamped = Math.min(50, Math.max(20, pct))
      setRightPanelWidth(clamped)
      localStorage.setItem('braindump-right-panel-width', String(clamped))
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
  }

  return (
    <div className="app">
      <HeaderBar multiUser={multiUser} />
      <div className="app-panels">
      <NavBar
        activeView={activeNav}
        pendingCount={pendingCount}
        onAddSpike={() => setRightPanel({ mode: 'editor', spike: null })}
        onViewChange={setActiveNav}
        onUpdatePending={handleUpdatePending}
        onRepair={handleRepair}
      />

      {/* Left sidebar */}
      <aside className="sidebar">
        <SearchBar value={search} onChange={setSearch} />
        <SpikeList
          spikes={filteredSpikes}
          selectedId={selectedSpikeId}
          onSelect={handleSpikeSelect}
          onUpdateWiki={handleUpdateWiki}
        />
        <StatusBar syncing={isSyncing} healthCheck={isHealthCheck} isSummarizing={summarizingStreams.size > 0 || summarizingDailies.size > 0} totalCostUsd={totalCostUsd} totalTokens={totalTokens} syncCount={syncCount} />
      </aside>

      {/* Main area */}
      <main className="main">
        {activeNav === 'streams' ? (
          <div className="main-view-slot">
            <StreamsView
              spikes={spikes}
              streams={streams}
              summarizingStreams={summarizingStreams}
              selectedId={selectedSpikeId}
              onSelect={handleSpikeSelect}
              onShowSummary={handleShowSummary}
              onTriggerSummary={handleTriggerSummary}
            />
          </div>
        ) : activeNav === 'dailies' ? (
          <div className="main-view-slot">
            <DailiesView
              spikes={spikes}
              dailies={dailies}
              summarizingDailies={summarizingDailies}
              selectedId={selectedSpikeId}
              onSelect={handleSpikeSelect}
              onShowSummary={handleShowDailySummary}
              onTriggerSummary={handleTriggerDailySummary}
            />
          </div>
        ) : (
          <>
            {/* View toggle tab bar */}
            <div className="main-tab-bar">
              <div className="main-tabs">
                <button
                  className={`main-tab${mainView === 'hierarchy' ? ' active' : ''}`}
                  onClick={handleSwitchToHierarchy}
                >
                  Browse
                </button>
                <button
                  className={`main-tab${mainView === 'graph' ? ' active' : ''}`}
                  onClick={() => setMainView('graph')}
                >
                  Graph
                </button>
              </div>
            </div>

            {/* Graph — hidden but NOT unmounted to preserve the Cytoscape instance */}
            <div className={`main-view-slot${mainView === 'graph' ? '' : ' hidden'}`}>
              <GraphView
                nodes={graphData.nodes}
                edges={graphData.edges}
                selectedSpikeId={selectedSpikeId}
                selectedSectionHeading={selectedSectionHeading}
                zoomLevel={zoomLevel}
                onZoomChange={(level: 0 | 1 | 2) => setZoomLevel(level)}
                onNodeClick={handleNodeClick}
                spikes={spikes}
              />
            </div>

            {/* Hierarchy browse — only rendered when active */}
            {mainView === 'hierarchy' && (
              <div className="main-view-slot">
                <HierarchyView
                  spikes={filteredSpikes}
                  allSpikes={spikes}
                  groupMode={hierarchyGroupMode}
                  onGroupModeChange={setHierarchyGroupMode}
                  communityData={hierarchyData}
                  communityLoading={hierarchyLoading}
                  selectedId={selectedSpikeId}
                  onSelect={handleSpikeSelect}
                />
              </div>
            )}
          </>
        )}
        <QueryBar onSourceClick={(spikeId, section) => handleNodeClick({ spikeId, sectionHeading: section })} />
      </main>

      {/* Right panel — editor or detail */}
      {rightPanel && (
        <div className={`right-panel-handle${isResizing ? ' resizing' : ''}`} onMouseDown={handleResizeMouseDown} />
      )}
      {rightPanel && (
        <aside className="right-panel" style={{ width: `${rightPanelWidth}vw` }}>
          {rightPanel.mode === 'editor' ? (
            <SpikeEditor
              key={rightPanel.spike?.id ?? 'new'}
              spike={rightPanel.spike}
              allTags={allTags}
              allStreams={allStreams}
              onSave={handleSave}
              onCancel={() => {
                if (rightPanel.spike) {
                  setRightPanel({ mode: 'detail', spike: rightPanel.spike, highlightSection: null })
                } else {
                  setRightPanel(null)
                }
              }}
              onClose={() => setRightPanel(null)}
            />
          ) : rightPanel.mode === 'stream-summary' ? (
            <StreamSummaryPanel
              streamName={rightPanel.streamName}
              content={rightPanel.content}
              generatedAt={rightPanel.generatedAt}
              onClose={() => setRightPanel(null)}
            />
          ) : rightPanel.mode === 'daily-summary' ? (
            <StreamSummaryPanel
              streamName={rightPanel.date}
              content={rightPanel.content}
              generatedAt={rightPanel.generatedAt}
              onClose={() => setRightPanel(null)}
            />
          ) : (
            <SpikeDetail
              spike={rightPanel.spike}
              highlightSection={rightPanel.highlightSection}
              onEdit={() => setRightPanel({ mode: 'editor', spike: rightPanel.spike })}
              onDelete={() => handleDelete(rightPanel.spike.id)}
              onClose={() => setRightPanel(null)}
            />
          )}
        </aside>
      )}
      </div>
    </div>
  )
}
