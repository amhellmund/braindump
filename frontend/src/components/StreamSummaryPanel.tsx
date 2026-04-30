import { formatDatetime } from '../utils'
import MarkdownPreview from './MarkdownPreview'
import './StreamSummaryPanel.css'

interface Props {
  streamName: string
  content: string
  generatedAt: string
  onClose: () => void
}

export default function StreamSummaryPanel({ streamName, content, generatedAt, onClose }: Props) {
  return (
    <div className="stream-summary-panel">
      <div className="summary-toolbar">
        <div className="summary-toolbar-left">
          <span className="summary-title">Stream Summary</span>
          <span className="summary-stream-name">{streamName}</span>
        </div>
        <div className="summary-actions">
          <button className="btn-close" onClick={onClose}>✕</button>
        </div>
      </div>

      <div className="summary-meta">
        <div className="summary-meta-item">
          <span className="summary-meta-label">Generated</span>
          <span className="summary-meta-value">{formatDatetime(generatedAt)}</span>
        </div>
      </div>

      <div className="summary-body">
        <MarkdownPreview raw={content} stripFrontmatter={false} />
      </div>
    </div>
  )
}
