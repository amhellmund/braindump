import { useState, useEffect, useRef } from 'react'
import { EditorView, keymap, lineNumbers } from '@codemirror/view'
import { EditorState, Prec } from '@codemirror/state'
import { markdown } from '@codemirror/lang-markdown'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import { tags } from '@lezer/highlight'
import { Spike } from '../types'
import { formatDatetime } from '../utils'
import { uploadImage } from '../api'
import { useErrorToast } from './ErrorToastContext'
import MarkdownPreview from './MarkdownPreview'
import TagsInput from './TagsInput'
import './SpikeEditor.css'

const darkTheme = EditorView.theme({
  '&': { height: '100%' },
  '.cm-content': {
    fontFamily: "'JetBrains Mono','Fira Code','Menlo',monospace",
    fontSize: '13px',
    lineHeight: '1.7',
    padding: '16px 16px 16px 0',
    caretColor: 'var(--text-primary)',
  },
  '.cm-gutters': {
    background: 'var(--surface)',
    borderRight: 'none',
    color: 'var(--text-muted)',
    fontSize: '11px',
    minWidth: '36px',
    paddingRight: '8px',
    userSelect: 'none',
  },
  '.cm-lineNumbers .cm-gutterElement': { textAlign: 'right', paddingLeft: '4px' },
  '.cm-activeLine': { background: 'transparent' },
  '.cm-activeLineGutter': { background: 'transparent' },
  '.cm-selectionBackground': { background: 'var(--surface-active) !important' },
  '&.cm-focused .cm-selectionBackground': { background: 'var(--surface-active) !important' },
  '.cm-focused': { outline: 'none' },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': { overflow: 'auto' },
  '.cm-cursor': { borderLeftColor: 'var(--text-primary)' },
}, { dark: true })

const markdownHighlight = syntaxHighlighting(HighlightStyle.define([
  { tag: tags.heading1,    color: '#a5b4fc', fontWeight: 'bold', fontSize: '1.1em' },
  { tag: tags.heading2,    color: '#93c5fd', fontWeight: 'bold' },
  { tag: tags.heading3,    color: '#7dd3fc', fontWeight: 'bold' },
  { tag: tags.strong,      color: '#f1f5f9', fontWeight: 'bold' },
  { tag: tags.emphasis,    color: '#d1d5db', fontStyle: 'italic' },
  { tag: tags.link,        color: '#60a5fa' },
  { tag: tags.url,         color: '#6b7e96' },
  { tag: tags.punctuation, color: '#6b7e96' },
]))

interface Props {
  spike: Spike | null
  allTags: string[]
  onSave: (body: string, tags: string[]) => void
  onCancel: () => void
  onClose: () => void
}

const NEW_BODY = `# New spike\n\n## \n\n`

function extractBody(raw: string): string {
  return raw.replace(/^---[\s\S]*?---\n/, '').trimStart()
}

export default function SpikeEditor({ spike, allTags, onSave, onCancel, onClose }: Props) {
  const { pushError } = useErrorToast()
  const [body, setBody] = useState(spike ? extractBody(spike.raw) : NEW_BODY)
  const [tags, setTags] = useState<string[]>(spike?.tags ?? [])
  const [preview, setPreview] = useState(false)
  const editorContainerRef = useRef<HTMLDivElement>(null)
  const editorViewRef = useRef<EditorView | null>(null)
  // Evergreen ref so the keymap closure always sees the current save handler
  const handleSaveRef = useRef<() => void>(() => {})

  const today = new Date().toISOString().slice(0, 10)
  const createdAt = spike?.createdAt ?? today
  const modifiedAt = spike?.modifiedAt ?? today

  const originalBody = spike ? extractBody(spike.raw) : NEW_BODY
  const originalTags = spike?.tags ?? []
  const isDirty = body !== originalBody || tags.join(',') !== originalTags.join(',')

  const handleSave = () => { if (isDirty) onSave(body, tags) }

  useEffect(() => { handleSaveRef.current = handleSave })

  // Create the CodeMirror editor once on mount; hide/show via CSS for preview toggle
  useEffect(() => {
    if (!editorContainerRef.current) return

    const initialDoc = spike ? extractBody(spike.raw) : NEW_BODY

    const view = new EditorView({
      state: EditorState.create({
        doc: initialDoc,
        extensions: [
          markdown(),
          lineNumbers(),
          darkTheme,
          markdownHighlight,
          keymap.of([{ key: 'Ctrl-Enter', run: () => { handleSaveRef.current(); return true } }]),
          // markdown()'s Enter handler suppresses newlines on already-empty trailing lines;
          // override with highest priority so trailing blank lines can be added freely
          Prec.highest(keymap.of([{
            key: 'Enter',
            run: (view) => {
              const { state } = view
              const { from } = state.selection.main
              if (from === state.doc.length && state.doc.lineAt(from).text === '') {
                view.dispatch({
                  changes: { from, to: from, insert: '\n' },
                  selection: { anchor: from + 1 },
                })
                return true
              }
              return false
            },
          }])),
          EditorView.domEventHandlers({
            paste(e: ClipboardEvent) {
              const imageItem = Array.from(e.clipboardData?.items ?? [])
                .find(item => item.type.startsWith('image/'))
              if (!imageItem) return false
              e.preventDefault()
              const file = imageItem.getAsFile()
              if (!file) return true
              const { from, to } = view.state.selection.main
              uploadImage(file)
                .then(({ url }) => {
                  const md = `![image](${url})`
                  view.dispatch({
                    changes: { from, to, insert: md },
                    selection: { anchor: from + md.length },
                  })
                })
                .catch((err: unknown) => pushError('Image upload failed', String(err)))
              return true
            },
          }),
          EditorView.updateListener.of(update => {
            if (update.docChanged) setBody(update.state.doc.toString())
          }),
        ],
      }),
      parent: editorContainerRef.current,
    })

    editorViewRef.current = view

    if (!spike) {
      const titleStart = 2
      view.dispatch({ selection: { anchor: titleStart, head: titleStart + 'New spike'.length } })
    }
    view.focus()

    return () => view.destroy()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps -- editor created once on mount

  return (
    <div className="spike-editor">

      {/* ── Toolbar ── */}
      <div className="editor-toolbar">
        <div className="editor-toolbar-left">
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

      {/* ── Body — both panels always mounted; CSS hides the inactive one ── */}
      {preview && (
        <div className="preview">
          <MarkdownPreview raw={body} stripFrontmatter={false} />
        </div>
      )}
      <div
        ref={editorContainerRef}
        className={`editor-cm-host${preview ? ' editor-cm-hidden' : ''}`}
      />
    </div>
  )
}
