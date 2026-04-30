import { useEffect, useRef } from 'react'
import { Spike, Section } from '../types'
import { formatDatetime } from '../utils'
import MarkdownPreview from './MarkdownPreview'
import './SpikeDetail.css'

interface Props {
  spike: Spike
  highlightSection: string | null   // heading of section to highlight (from graph click)
  onEdit: () => void
  onDelete: () => void
  onClose: () => void
}

export default function SpikeDetail({ spike, highlightSection, onEdit, onDelete, onClose }: Props) {
  const handleDelete = () => {
    if (window.confirm(`Delete "${spike.title}"? This cannot be undone.`)) {
      onDelete()
    }
  }

  return (
    <div className="spike-detail">
      <div className="detail-toolbar">
        <div className="detail-toolbar-left">
          <span className="detail-title">Spike Viewer</span>
        </div>
        <div className="detail-actions">
          <button className="btn-toggle" onClick={onEdit}>Edit</button>
          <button className="btn-delete" onClick={handleDelete} title="Delete spike">Delete</button>
          <button className="btn-close" onClick={onClose}>✕</button>
        </div>
      </div>

      <div className="detail-meta">
        <div className="detail-date-item">
          <span className="detail-date-label">Created</span>
          <span className="detail-date-value">{formatDatetime(spike.createdAt)}</span>
        </div>
        <div className="detail-date-item">
          <span className="detail-date-label">Modified</span>
          <span className="detail-date-value">{formatDatetime(spike.modifiedAt)}</span>
        </div>
        <div className="detail-tags">
          {spike.tags.map(t => (
            <span key={t} className="tag">{t}</span>
          ))}
        </div>
      </div>

      <div className="detail-body">
        <h1 className="detail-body-title">{spike.title}</h1>
        {spike.sections.map((section, idx) => (
          <SectionBlock
            key={section.heading ?? `intro-${idx}`}
            section={section}
            highlighted={section.heading !== null && section.heading === highlightSection}
          />
        ))}
      </div>
    </div>
  )
}

function SectionBlock({ section, highlighted }: { section: Section; highlighted: boolean }) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (highlighted && ref.current) {
      ref.current.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [highlighted])

  return (
    <div ref={ref} className={`section-block ${highlighted ? 'highlighted' : ''}`}>
      {section.heading !== null && <h2 className="section-heading">{section.heading}</h2>}
      <MarkdownPreview raw={section.content} stripFrontmatter={false} />
    </div>
  )
}
