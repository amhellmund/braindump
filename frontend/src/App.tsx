import { useState, useMemo, useRef, useCallback, useEffect } from 'react'
import { Spike } from './types'
import { fetchSpikes, fetchGraph, fetchStatus, createSpike, updateSpike, deleteSpike, GraphData } from './api'
import SearchBar from './components/SearchBar'
import SpikeList from './components/SpikeList'
import SpikeEditor from './components/SpikeEditor'
import SpikeDetail from './components/SpikeDetail'
import GraphView from './components/GraphView'
import HierarchyView from './components/HierarchyView'
import QueryBar from './components/QueryBar'
import StatusBar from './components/StatusBar'
import NavBar, { NavView } from './components/NavBar'
import HeaderBar from './components/HeaderBar'
import { ErrorToastProvider, useErrorToast } from './components/ErrorToast'
import './App.css'

type RightPanel = { mode: 'editor'; spike: Spike | null }
                | { mode: 'detail'; spike: Spike; highlightSection: string | null }
                | null

export default function App() {
  return (
    <ErrorToastProvider>
      <AppInner />
    </ErrorToastProvider>
  )
}

function AppInner() {
  const { pushError } = useErrorToast()
  const [spikes, setSpikes] = useState<Spike[]>([])
  const [search, setSearch] = useState('')
  const [selectedSpikeId, setSelectedSpikeId] = useState<string | null>(null)
  const [selectedSectionHeading, setSelectedSectionHeading] = useState<string | null>(null)
  const [rightPanel, setRightPanel] = useState<RightPanel>(null)
  const [zoomLevel, setZoomLevel] = useState<0 | 1 | 2>(2)
  const [isExpanded, setIsExpanded] = useState(false)
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

  useEffect(() => {
    fetchSpikes()
      .then(setSpikes)
      .catch((err: unknown) => pushError('Failed to load spikes', String(err)))
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
      ws = new WebSocket(`${proto}//${window.location.host}/api/v1/ws`)

      ws.onopen = () => {
        backoffMs = 1000  // reset backoff after a successful connection
      }

      ws.onmessage = (event: MessageEvent) => {
        try {
          const msg = JSON.parse(event.data as string) as {
            type: string
            spike_id?: string | null
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

  // Save a spike — receives body (no frontmatter) and tags separately
  const handleSave = async (body: string, tags: string[]) => {
    const editingSpike = rightPanel?.mode === 'editor' ? rightPanel.spike : null
    const raw = `---\ntags: [${tags.join(', ')}]\n---\n\n${body}`

    try {
      if (editingSpike) {
        const updated = await updateSpike(editingSpike.id, raw)
        setSpikes(prev => prev.map(s => s.id === editingSpike.id ? updated : s))
        setRightPanel({ mode: 'detail', spike: updated, highlightSection: null })
      } else {
        const newSpike = await createSpike(raw)
        setSpikes(prev => [newSpike, ...prev])
        setSelectedSpikeId(newSpike.id)
        setRightPanel({ mode: 'detail', spike: newSpike, highlightSection: null })
      }
    } catch (err: unknown) {
      pushError('Failed to save spike', String(err))
    }
  }

  return (
    <div className="app">
      <HeaderBar />
      <div className="app-panels">
      <NavBar
        activeView={activeNav}
        onAddSpike={() => setRightPanel({ mode: 'editor', spike: null })}
        onViewChange={setActiveNav}
      />

      {/* Left sidebar */}
      <aside className="sidebar">
        <SearchBar value={search} onChange={setSearch} />
        <SpikeList
          spikes={filteredSpikes}
          selectedId={selectedSpikeId}
          onSelect={handleSpikeSelect}
        />
        <StatusBar syncing={isSyncing} healthCheck={isHealthCheck} totalCostUsd={totalCostUsd} totalTokens={totalTokens} syncCount={syncCount} />
      </aside>

      {/* Main area */}
      <main className="main">
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
              groupMode={hierarchyGroupMode}
              onGroupModeChange={setHierarchyGroupMode}
              communityData={hierarchyData}
              communityLoading={hierarchyLoading}
              selectedId={selectedSpikeId}
              onSelect={handleSpikeSelect}
            />
          </div>
        )}

        <QueryBar onSourceClick={(spikeId, section) => handleNodeClick({ spikeId, sectionHeading: section })} />
      </main>

      {/* Right panel — editor or detail */}
      {rightPanel && (
        <aside className={`right-panel${isExpanded ? ' expanded' : ''}`}>
          {rightPanel.mode === 'editor' ? (
            <SpikeEditor
              key={rightPanel.spike?.id ?? 'new'}
              spike={rightPanel.spike}
              allTags={allTags}
              expanded={isExpanded}
              onSave={handleSave}
              onCancel={() => {
                if (rightPanel.spike) {
                  setRightPanel({ mode: 'detail', spike: rightPanel.spike, highlightSection: null })
                } else {
                  setRightPanel(null)
                }
              }}
              onClose={() => setRightPanel(null)}
              onExpandToggle={() => setIsExpanded(p => !p)}
            />
          ) : (
            <SpikeDetail
              spike={rightPanel.spike}
              highlightSection={rightPanel.highlightSection}
              expanded={isExpanded}
              onEdit={() => setRightPanel({ mode: 'editor', spike: rightPanel.spike })}
              onDelete={() => handleDelete(rightPanel.spike.id)}
              onClose={() => setRightPanel(null)}
              onExpandToggle={() => setIsExpanded(p => !p)}
            />
          )}
        </aside>
      )}
      </div>
    </div>
  )
}
