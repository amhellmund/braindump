export interface Section {
  heading: string | null
  content: string
}

export interface Spike {
  id: string
  title: string
  tags: string[]
  createdAt: string
  modifiedAt: string
  raw: string        // full markdown source (frontmatter + body)
  sections: Section[]
  stream: string | null
}

export interface GraphNode {
  id: string
  label: string
  type: 'spike' | 'cluster'
  tags?: string[]
  zoomLevel: 0 | 1 | 2
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  type: 'tag' | 'semantic' | 'temporal' | 'cluster'
}
