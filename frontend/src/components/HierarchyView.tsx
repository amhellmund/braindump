import { useState, useMemo } from 'react'
import { Spike } from '../types'
import { GraphData } from '../api'
import { formatDatetime } from '../utils'
import './HierarchyView.css'

interface Props {
  spikes: Spike[]
  allSpikes: Spike[]
  groupMode: 'community' | 'tag'
  onGroupModeChange: (mode: 'community' | 'tag') => void
  communityData: GraphData | null
  communityLoading: boolean
  selectedId: string | null
  onSelect: (spike: Spike) => void
}

interface Group {
  key: string
  label: string
  spikes: Spike[]
}

function buildCommunityGroups(spikes: Spike[], communityData: GraphData): Group[] {
  // Build a map from cluster node id → group
  const groups = new Map<string, Group>()
  for (const node of communityData.nodes) {
    if (node.type === 'cluster') {
      groups.set(node.id, { key: node.id, label: node.label, spikes: [] })
    }
  }

  // Track which spike IDs were assigned to a cluster
  const assigned = new Set<string>()
  for (const edge of communityData.edges) {
    if (edge.type === 'cluster') {
      const group = groups.get(edge.target)
      const spike = spikes.find(s => s.id === edge.source)
      if (group && spike) {
        group.spikes.push(spike)
        assigned.add(spike.id)
      }
    }
  }

  // Spikes not in any cluster → "Unclustered" at the end
  const unclustered = spikes.filter(s => !assigned.has(s.id))

  const result = [...groups.values()]
    .sort((a, b) => a.label.localeCompare(b.label))

  if (unclustered.length > 0) {
    result.push({ key: '__unclustered__', label: 'Unclustered', spikes: unclustered })
  }

  // Sort spikes within each group by modifiedAt descending
  for (const g of result) {
    g.spikes.sort((a, b) => b.modifiedAt.localeCompare(a.modifiedAt))
  }

  return result
}

function buildTagGroups(spikes: Spike[]): Group[] {
  const tagSet = new Set<string>()
  for (const spike of spikes) {
    for (const tag of spike.tags) tagSet.add(tag)
  }

  const result: Group[] = [...tagSet]
    .sort((a, b) => a.localeCompare(b))
    .map(tag => ({
      key: `tag:${tag}`,
      label: tag,
      spikes: spikes
        .filter(s => s.tags.includes(tag))
        .sort((a, b) => b.modifiedAt.localeCompare(a.modifiedAt)),
    }))

  const untagged = spikes
    .filter(s => s.tags.length === 0)
    .sort((a, b) => b.modifiedAt.localeCompare(a.modifiedAt))

  if (untagged.length > 0) {
    result.push({ key: '__untagged__', label: 'Untagged', spikes: untagged })
  }

  return result
}

// ── Search helpers ───────────────────────────────────────────────────────────

function highlightText(text: string, query: string): React.ReactNode {
  const lower = text.toLowerCase()
  const q = query.toLowerCase()
  const idx = lower.indexOf(q)
  if (idx === -1) return text
  return (
    <>
      {text.slice(0, idx)}
      <strong className="hierarchy-search-match">{text.slice(idx, idx + query.length)}</strong>
      {text.slice(idx + query.length)}
    </>
  )
}

interface Snippet {
  before: string
  match: string
  after: string
}

function extractSnippet(raw: string, query: string): Snippet | null {
  // Strip YAML frontmatter and collapse newlines for readable context
  const content = raw.replace(/^---\n[\s\S]*?\n---\n?/, '').replace(/\n+/g, ' ').trim()
  const lower = content.toLowerCase()
  const idx = lower.indexOf(query.toLowerCase())
  if (idx === -1) return null

  const BEFORE = 60
  const AFTER = 100
  const start = Math.max(0, idx - BEFORE)
  const end = Math.min(content.length, idx + query.length + AFTER)

  const before = (start > 0 ? '…' : '') + content.slice(start, idx)
  const match = content.slice(idx, idx + query.length)
  const after = content.slice(idx + query.length, end) + (end < content.length ? '…' : '')

  return { before, match, after }
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
      className={`hierarchy-spike-row${selected ? ' selected' : ''}`}
      onClick={() => onSelect(spike)}
      role="button"
      tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && onSelect(spike)}
      aria-label={spike.title}
    >
      <div className="hierarchy-spike-title">
        <span>{spike.title}</span>
      </div>
      <div className="hierarchy-spike-meta">
        <span className="spike-list-date">{formatDatetime(spike.modifiedAt)}</span>
        <span className="spike-list-tags">
          {spike.tags.map(t => <span key={t} className="tag">{t}</span>)}
        </span>
      </div>
    </div>
  )
}

// ── Search result row (title highlight + content snippet) ────────────────────

interface SearchResultRowProps {
  spike: Spike
  query: string
  selected: boolean
  onSelect: (spike: Spike) => void
}

function SearchResultRow({ spike, query, selected, onSelect }: SearchResultRowProps) {
  const snippet = extractSnippet(spike.raw, query)

  return (
    <div
      className={`hierarchy-spike-row${selected ? ' selected' : ''}`}
      onClick={() => onSelect(spike)}
      role="button"
      tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && onSelect(spike)}
      aria-label={spike.title}
    >
      <div className="hierarchy-spike-title">
        <span>{highlightText(spike.title, query)}</span>
      </div>
      <div className="hierarchy-spike-meta">
        <span className="spike-list-date">{formatDatetime(spike.modifiedAt)}</span>
        <span className="spike-list-tags">
          {spike.tags.map(t => <span key={t} className="tag">{t}</span>)}
        </span>
      </div>
      {snippet && (
        <div className="hierarchy-search-snippet">
          {snippet.before}
          <strong className="hierarchy-search-match">{snippet.match}</strong>
          {snippet.after}
        </div>
      )}
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────

export default function HierarchyView({
  spikes,
  allSpikes,
  groupMode,
  onGroupModeChange,
  communityData,
  communityLoading,
  selectedId,
  onSelect,
}: Props) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [searchQuery, setSearchQuery] = useState('')
  const [activeQuery, setActiveQuery] = useState('')

  const toggleCollapsed = (key: string) => {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const groups = useMemo<Group[]>(() => {
    if (groupMode === 'community') {
      if (!communityData) return []
      return buildCommunityGroups(spikes, communityData)
    }
    return buildTagGroups(spikes)
  }, [spikes, groupMode, communityData])

  const searchResults = useMemo<Spike[]>(() => {
    const q = activeQuery.trim().toLowerCase()
    if (!q) return []
    return allSpikes
      .filter(s =>
        s.title.toLowerCase().includes(q) ||
        s.tags.some(t => t.toLowerCase().includes(q)) ||
        s.raw.toLowerCase().includes(q)
      )
      .sort((a, b) => b.modifiedAt.localeCompare(a.modifiedAt))
  }, [allSpikes, activeQuery])

  const isSearchActive = activeQuery.trim().length > 0

  const handleSearchSubmit = () => setActiveQuery(searchQuery)

  const handleSearchKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') handleSearchSubmit()
    if (e.key === 'Escape') handleClearSearch()
  }

  const handleClearSearch = () => {
    setSearchQuery('')
    setActiveQuery('')
  }

  const showLoading = communityLoading && groupMode === 'community'
  const showEmpty = !showLoading && groups.length === 0

  return (
    <div className="hierarchy-view">
      <div className="hierarchy-toolbar">
        <span className="hierarchy-group-label">Group by</span>
        <button
          className={`zoom-btn${groupMode === 'community' ? ' active' : ''}`}
          onClick={() => onGroupModeChange('community')}
        >
          Community
        </button>
        <button
          className={`zoom-btn${groupMode === 'tag' ? ' active' : ''}`}
          onClick={() => onGroupModeChange('tag')}
        >
          Tag
        </button>
        {communityLoading && <span className="sync-spinner" title="Loading communities…" aria-label="Loading communities" />}

        <div className="hierarchy-search-inline">
          <input
            className="hierarchy-search-input"
            type="text"
            placeholder="Search all spikes…"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            onKeyDown={handleSearchKeyDown}
            aria-label="Full-text search"
          />
          {isSearchActive && (
            <button className="hierarchy-search-clear" onClick={handleClearSearch} aria-label="Clear search">✕</button>
          )}
          <button
            className="hierarchy-search-btn"
            onClick={handleSearchSubmit}
            disabled={!searchQuery.trim()}
          >
            Search
          </button>
        </div>
      </div>

      {isSearchActive ? (
        <div className="hierarchy-body">
          <div className="hierarchy-search-count">
            {searchResults.length === 0
              ? 'No results.'
              : `${searchResults.length} result${searchResults.length === 1 ? '' : 's'}`}
          </div>
          {searchResults.map(spike => (
            <SearchResultRow
              key={spike.id}
              spike={spike}
              query={activeQuery.trim()}
              selected={spike.id === selectedId}
              onSelect={onSelect}
            />
          ))}
        </div>
      ) : (
        <div className="hierarchy-body">
          {showLoading && (
            <div className="hierarchy-empty">Loading communities…</div>
          )}
          {showEmpty && (
            <div className="hierarchy-empty">No spikes match.</div>
          )}
          {groups.map(group => (
            <div key={group.key} className="hierarchy-group">
              <button
                className="hierarchy-group-header"
                onClick={() => toggleCollapsed(group.key)}
                aria-expanded={!collapsed.has(group.key)}
              >
                <span className={`hierarchy-chevron${collapsed.has(group.key) ? ' collapsed' : ''}`}>▾</span>
                <span className="hierarchy-group-name">{group.label}</span>
                <span className="hierarchy-group-count">{group.spikes.length}</span>
              </button>
              {!collapsed.has(group.key) && (
                <div className="hierarchy-group-items">
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
          ))}
        </div>
      )}
    </div>
  )
}
