import { useState, useRef, useEffect, KeyboardEvent } from 'react'
import './TagsInput.css'

interface Props {
  value: string[]
  onChange: (tags: string[]) => void
  suggestions: string[]    // all known tags across the corpus
  onCtrlEnter?: () => void
}

export default function TagsInput({ value, onChange, suggestions, onCtrlEnter }: Props) {
  const [input, setInput] = useState('')
  const [open, setOpen] = useState(false)
  const [highlightIndex, setHighlightIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const filtered = suggestions.filter(
    s => s.toLowerCase().includes(input.toLowerCase()) && !value.includes(s)
  )

  const addTag = (tag: string) => {
    const trimmed = tag.trim().toLowerCase()
    if (trimmed && !value.includes(trimmed)) {
      onChange([...value, trimmed])
    }
    setInput('')
    setOpen(false)
    setHighlightIndex(0)
    inputRef.current?.focus()
  }

  const removeTag = (tag: string) => {
    onChange(value.filter(t => t !== tag))
    inputRef.current?.focus()
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.ctrlKey && e.key === 'Enter') {
      e.preventDefault()
      onCtrlEnter?.()
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlightIndex(i => Math.min(i + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlightIndex(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (open && filtered[highlightIndex]) {
        addTag(filtered[highlightIndex])
      } else if (input.trim()) {
        addTag(input)
      }
    } else if (e.key === 'Escape') {
      setOpen(false)
    } else if (e.key === 'Backspace' && input === '' && value.length > 0) {
      onChange(value.slice(0, -1))
    }
  }

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

return (
    <div className="tags-input-wrap" ref={containerRef}>
      <div
        className="tags-input-field"
        onClick={() => inputRef.current?.focus()}
      >
        {value.map(tag => (
          <span key={tag} className="tags-chip">
            {tag}
            <button
              className="tags-chip-remove"
              onMouseDown={e => { e.preventDefault(); removeTag(tag) }}
              tabIndex={-1}
            >×</button>
          </span>
        ))}
        <input
          ref={inputRef}
          className="tags-input"
          value={input}
          placeholder={value.length === 0 ? 'Add tags…' : ''}
          onChange={e => { setInput(e.target.value); setOpen(true); setHighlightIndex(0) }}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
        />
      </div>

      {open && filtered.length > 0 && (
        <ul className="tags-dropdown">
          {filtered.map((s, i) => (
            <li
              key={s}
              className={`tags-dropdown-item ${i === highlightIndex ? 'highlighted' : ''}`}
              onMouseDown={e => { e.preventDefault(); addTag(s) }}
              onMouseEnter={() => setHighlightIndex(i)}
            >
              {s}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
