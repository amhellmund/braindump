import { useState, useEffect, useRef, useCallback } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faExpand, faCompress } from '@fortawesome/free-solid-svg-icons'
import { Spike } from '../types'
import { formatDatetime } from '../utils'
import { uploadImage } from '../api'
import { useErrorToast } from './ErrorToast'
import MarkdownPreview from './MarkdownPreview'
import TagsInput from './TagsInput'
import './SpikeEditor.css'

interface Props {
  spike: Spike | null        // null = new spike
  allTags: string[]          // all known tags across the corpus
  expanded: boolean
  onSave: (body: string, tags: string[]) => void
  onCancel: () => void
  onClose: () => void
  onExpandToggle: () => void
}

const NEW_BODY = `# New spike\n\n## \n\n`

function extractBody(raw: string): string {
  return raw.replace(/^---[\s\S]*?---\n/, '').trimStart()
}

export default function SpikeEditor({ spike, allTags, expanded, onSave, onCancel, onClose, onExpandToggle }: Props) {
  const { pushError } = useErrorToast()
  const [body, setBody] = useState(spike ? extractBody(spike.raw) : NEW_BODY)
  const [tags, setTags] = useState<string[]>(spike?.tags ?? [])
  const [preview, setPreview] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (spike || !textareaRef.current) return
    // Select "New spike" (after the leading "# ") so the first keystroke replaces the title
    const titleStart = 2
    const titleEnd = titleStart + 'New spike'.length
    textareaRef.current.focus()
    textareaRef.current.setSelectionRange(titleStart, titleEnd)
  }, [])

const today = new Date().toISOString().slice(0, 10)
  const createdAt = spike?.createdAt ?? today
  const modifiedAt = spike?.modifiedAt ?? today

  const originalBody = spike ? extractBody(spike.raw) : NEW_BODY
  const originalTags = spike?.tags ?? []
  const isDirty = body !== originalBody || tags.join(',') !== originalTags.join(',')

  const handleSave = () => { if (isDirty) onSave(body, tags) }

  const handlePaste = useCallback(async (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const imageItem = Array.from(e.clipboardData.items).find(item => item.type.startsWith('image/'))
    if (!imageItem) return

    e.preventDefault()
    const file = imageItem.getAsFile()
    if (!file) return

    try {
      const { url } = await uploadImage(file)
      const markdown = `![image](${url})`
      const el = textareaRef.current
      if (!el) return
      const start = el.selectionStart
      const end = el.selectionEnd
      setBody(prev => prev.slice(0, start) + markdown + prev.slice(end))
      requestAnimationFrame(() => {
        el.selectionStart = el.selectionEnd = start + markdown.length
        el.focus()
      })
    } catch (err: unknown) {
      pushError('Image upload failed', String(err))
    }
  }, [pushError])

  return (
    <div className="spike-editor">

      {/* ── Toolbar ── */}
      <div className="editor-toolbar">
        <div className="editor-toolbar-left">
          <button
            className="btn-expand"
            onClick={onExpandToggle}
            title={expanded ? 'Shrink editor' : 'Expand editor'}
            aria-label={expanded ? 'Shrink editor' : 'Expand editor'}
          >
            <FontAwesomeIcon icon={expanded ? faCompress : faExpand} />
          </button>
          <span className="editor-title">{spike?.title ?? 'New spike'}</span>
        </div>
        <div className="editor-actions">
          <button
            className={`btn-toggle ${preview ? 'active' : ''}`}
            onClick={() => setPreview(p => !p)}
          >
            {preview ? 'Edit' : 'Preview'}
          </button>
          <button className="btn-toggle" onClick={onCancel}>Cancel</button>
          <button className="btn-save" disabled={!isDirty} onClick={handleSave}>
            Save
          </button>
          <button className="btn-close" onClick={onClose}>✕</button>
        </div>
      </div>

      {/* ── Metadata header ── */}
      <div className="editor-meta">
        <div className="editor-dates">
          <div className="editor-date-item">
            <span className="editor-date-label">Created</span>
            <span className="editor-date-value">{formatDatetime(createdAt)}</span>
          </div>
          <div className="editor-date-item">
            <span className="editor-date-label">Modified</span>
            <span className="editor-date-value">{formatDatetime(modifiedAt)}</span>
          </div>
        </div>
        <div className="editor-tags-row">
          <span className="editor-tags-label">Tags</span>
          <TagsInput
            value={tags}
            onChange={setTags}
            suggestions={allTags}
            onCtrlEnter={handleSave}
          />
        </div>
      </div>

      <div className="editor-divider" />

      {/* ── Body ── */}
      {preview ? (
        <div className="preview">
          <MarkdownPreview raw={body} stripFrontmatter={false} />
        </div>
      ) : (
        <textarea
          ref={textareaRef}
          className="editor-textarea"
          value={body}
          onChange={e => setBody(e.target.value)}
          onKeyDown={e => { if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); handleSave() } }}
          onPaste={handlePaste}
          spellCheck={false}
        />
      )}
    </div>
  )
}
