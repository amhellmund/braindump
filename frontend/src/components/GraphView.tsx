import { useEffect, useRef } from 'react'
import cytoscape, { Core } from 'cytoscape'
import { GraphNode, GraphEdge, Spike } from '../types'
import './GraphView.css'

interface GraphClickEvent {
  spikeId: string
  sectionHeading: string | null
}

interface Props {
  nodes: GraphNode[]
  edges: GraphEdge[]
  selectedSpikeId: string | null
  selectedSectionHeading: string | null
  zoomLevel: 0 | 1 | 2
  onZoomChange: (level: 0 | 1 | 2) => void
  onNodeClick: (event: GraphClickEvent) => void
  spikes: Spike[]
}

const EDGE_COLORS: Record<string, string> = {
  tag: '#6b8cba',
  semantic: '#8b5cf6',
  temporal: '#f59e0b',
  cluster: '#6b7280',
}

export default function GraphView({
  nodes, edges, selectedSpikeId, selectedSectionHeading, zoomLevel, onZoomChange, onNodeClick, spikes,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)
  const spikesRef = useRef(spikes)
  const onNodeClickRef = useRef(onNodeClick)

  // Keep refs in sync with latest props on every render
  useEffect(() => { spikesRef.current = spikes }, [spikes])
  useEffect(() => { onNodeClickRef.current = onNodeClick }, [onNodeClick])

  useEffect(() => {
    if (!containerRef.current) return

    const cy = cytoscape({
      container: containerRef.current,
      style: [
        {
          selector: 'node[type = "spike"]',
          style: {
            label: 'data(label)',
            'background-color': '#3b82f6',
            'border-color': '#1d4ed8',
            'border-width': 2,
            color: '#e2e8f0',
            'font-size': 9,
            'text-valign': 'bottom',
            'text-margin-y': 4,
            'text-wrap': 'wrap',
            'text-max-width': '80px',
            width: 24,
            height: 24,
          },
        },
        {
          selector: 'node[type = "cluster"]',
          style: {
            label: 'data(label)',
            'background-color': '#374151',
            'border-color': '#6b7280',
            'border-width': 2,
            'border-style': 'dashed',
            color: '#9ca3af',
            'font-size': 10,
            'font-weight': 'bold',
            'text-valign': 'center',
            width: 60,
            height: 60,
            shape: 'ellipse',
          },
        },
        {
          selector: 'node.selected',
          style: {
            'background-color': '#f97316',
            'border-color': '#ea580c',
            'border-width': 3,
            color: '#fff',
          },
        },
        {
          selector: 'edge',
          style: {
            width: 1.5,
            'line-color': '#374151',
            'target-arrow-shape': 'none',
            opacity: 0.6,
            'curve-style': 'bezier',
          },
        },
        {
          selector: 'edge[type = "tag"]',
          style: { 'line-color': EDGE_COLORS.tag },
        },
        {
          selector: 'edge[type = "semantic"]',
          style: { 'line-color': EDGE_COLORS.semantic, 'line-style': 'dashed' },
        },
        {
          selector: 'edge[type = "temporal"]',
          style: { 'line-color': EDGE_COLORS.temporal, 'line-style': 'dotted' },
        },
        {
          selector: 'edge[type = "cluster"]',
          style: { 'line-color': EDGE_COLORS.cluster, width: 2, opacity: 0.4 },
        },
      ],
      layout: { name: 'cose', animate: false } as cytoscape.LayoutOptions,
      userZoomingEnabled: true,
      userPanningEnabled: true,
    })

    cyRef.current = cy

    cy.on('tap', 'node', evt => {
      const nodeData = evt.target.data() as GraphNode
      if (nodeData.type !== 'spike') return
      const spike = spikesRef.current.find(s => s.id === nodeData.id)
      if (!spike) return
      const sectionHeading = spike.sections[0]?.heading ?? null
      onNodeClickRef.current({ spikeId: nodeData.id, sectionHeading })
    })

    return () => cy.destroy()
  }, [])

  // Sync elements when nodes/edges change
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return

    cy.elements().remove()
    cy.add([
      ...nodes.map(n => ({ group: 'nodes' as const, data: n })),
      ...edges.map(e => ({ group: 'edges' as const, data: e })),
    ])
    const layout = cy.layout({ name: 'cose', animate: true, animationDuration: 400 } as cytoscape.LayoutOptions)
    layout.on('layoutstop', () => { cy.fit(undefined, 80) })
    layout.run()
  }, [nodes, edges])

  // Highlight selected spike and section nodes
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.nodes().removeClass('selected')
    if (selectedSpikeId) {
      cy.$(`#${selectedSpikeId}`).addClass('selected')
    }
    if (selectedSpikeId && selectedSectionHeading) {
      cy.nodes(`[spikeId = "${selectedSpikeId}"][sectionHeading = "${selectedSectionHeading}"]`).addClass('selected')
    }
  }, [selectedSpikeId, selectedSectionHeading, nodes])

  return (
    <div className="graph-view">
      <div className="graph-toolbar">
        <div className="zoom-controls">
          <button
            className={`zoom-btn ${zoomLevel === 0 ? 'active' : ''}`}
            onClick={() => onZoomChange(0)}
            title="Macro view — topic bubbles"
          >
            Macro
          </button>
          <button
            className={`zoom-btn ${zoomLevel === 1 ? 'active' : ''}`}
            onClick={() => onZoomChange(1)}
            title="Mid view — clusters"
          >
            Clusters
          </button>
          <button
            className={`zoom-btn ${zoomLevel === 2 ? 'active' : ''}`}
            onClick={() => onZoomChange(2)}
            title="Spike view — individual spikes"
          >
            Spikes
          </button>
        </div>
        <div className="graph-legend">
          <>
            <span className="legend-item" style={{ color: EDGE_COLORS.tag }}>— tag</span>
            <span className="legend-item" style={{ color: EDGE_COLORS.semantic }}>- - semantic</span>
            <span className="legend-item" style={{ color: EDGE_COLORS.temporal }}>··· temporal</span>
          </>
        </div>
      </div>
      <div className="graph-container" ref={containerRef} />
    </div>
  )
}
