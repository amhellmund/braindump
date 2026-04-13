import { useEffect, useRef } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faExpand, faCompress } from '@fortawesome/free-solid-svg-icons'
import { Spike, Section } from '../types'
import { formatDatetime } from '../utils'
import MarkdownPreview from './MarkdownPreview'
import './SpikeDetail.css'

interface Props {
  spike: Spike
  highlightSection: string | null   // heading of section to highlight (from graph click)
  expanded: boolean
  onEdit: () => void
  onDelete: () => void
  onClose: () => void
  onExpandToggle: () => void
}

export default function SpikeDetail({ spike, highlightSection, expanded, onEdit, onDelete, onClose, onExpandToggle }: Props) {
  const handleDelete = () => {
    if (window.confirm(`Delete "${spike.title}"? This cannot be undone.`)) {
      onDelete()
    }
  }

  return (
    <div className="spike-detail">
      <div className="detail-toolbar">
        <div className="detail-toolbar-left">
          <button
            className="btn-expand"
            onClick={onExpandToggle}
            title={expanded ? 'Shrink' : 'Expand'}
            aria-label={expanded ? 'Shrink' : 'Expand'}
          >
            <FontAwesomeIcon icon={expanded ? faCompress : faExpand} />
          </button>
          <span className="detail-title">{spike.title}</span>
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
        {spike.sections.map(section => (
          <SectionBlock
            key={section.heading}
            section={section}
            highlighted={section.heading === highlightSection}
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
      <h2 className="section-heading">{section.heading}</h2>
      <MarkdownPreview raw={section.content} stripFrontmatter={false} />
    </div>
  )
}
