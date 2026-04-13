import { useState, useRef, useEffect } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faChevronDown, faChevronUp, faPlus } from '@fortawesome/free-solid-svg-icons'
import { ChatTurn, QuerySource, sendQuery } from '../api'
import { useErrorToast } from './ErrorToast'
import './QueryBar.css'

interface UserMessage {
  role: 'user'
  text: string
}

interface AssistantMessage {
  role: 'assistant'
  answer: string
  sources: QuerySource[]
}

type Message = UserMessage | AssistantMessage

interface Props {
  onSourceClick: (spikeId: string, section: string) => void
}

export default function QueryBar({ onSourceClick }: Props) {
  const { pushError } = useErrorToast()
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [expanded, setExpanded] = useState(true)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (expanded) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, expanded])

  const submit = async () => {
    if (!query.trim() || loading) return
    const text = query.trim()
    setQuery('')
    setExpanded(true)

    setMessages(prev => {
      const next = [...prev, { role: 'user' as const, text }]
      return next
    })
    setLoading(true)

    try {
      const history: ChatTurn[] = messages.map(m =>
        m.role === 'user'
          ? { role: 'user' as const, text: m.text }
          : { role: 'assistant' as const, text: m.answer }
      )
      const result = await sendQuery(text, history)
      setMessages(prev => [...prev, { role: 'assistant', answer: result.answer, sources: result.citations }])
    } catch (err: unknown) {
      pushError('Query failed', String(err))
      setMessages(prev => [...prev, { role: 'assistant', answer: 'Something went wrong. Please try again.', sources: [] }])
    } finally {
      setLoading(false)
    }
  }

  const newSession = () => {
    setMessages([])
    setQuery('')
    setExpanded(true)
  }

  const hasMessages = messages.length > 0

  return (
    <div className="query-bar">
      {/* Chat history overlay */}
      {hasMessages && expanded && (
        <div className="query-chat">
          {messages.map((msg, i) =>
            msg.role === 'user' ? (
              <div key={i} className="chat-user-message">
                <span className="chat-user-label">You</span>
                <p className="chat-user-text">{msg.text}</p>
              </div>
            ) : (
              <div key={i} className="chat-assistant-message">
                <span className="chat-assistant-label">braindump</span>
                <div className="query-answer">
                  <p className="query-text-block">
                    <InlineText text={msg.answer} />
                  </p>
                </div>
                {msg.sources.length > 0 && (
                  <>
                    <div className="query-sources-header">Sources</div>
                    <div className="query-sources">
                      {msg.sources.map(s => (
                        <div
                          key={s.index}
                          className="query-source-card"
                          onClick={() => onSourceClick(s.spikeId, s.section)}
                        >
                          <div className="source-card-top">
                            <span className="source-index">{s.index}</span>
                            <span className="source-title">{s.title}</span>
                            <span className="source-section">› {s.section}</span>
                          </div>
                          <p className="source-snippet">{s.snippet}</p>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )
          )}
          {loading && (
            <div className="chat-assistant-message">
              <span className="chat-assistant-label">braindump</span>
              <div className="chat-thinking">
                <span /><span /><span />
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      )}

      {/* Input row */}
      <div className="query-input-row">
        <button
          className="query-icon-btn"
          onClick={() => setExpanded(e => !e)}
          title={expanded ? 'Collapse chat' : 'Expand chat'}
          disabled={!hasMessages}
        >
          <FontAwesomeIcon icon={expanded ? faChevronDown : faChevronUp} />
        </button>
        <button
          className="query-icon-btn"
          onClick={newSession}
          title="New session"
        >
          <FontAwesomeIcon icon={faPlus} />
        </button>
        <input
          type="text"
          className="query-input"
          placeholder="Ask a question across all spikes…"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && submit()}
        />
        <button className="query-submit" onClick={submit} disabled={loading || !query.trim()}>
          Ask
        </button>
      </div>
    </div>
  )
}

// ── Inline text renderer ─────────────────────────────────────────────────────

function InlineText({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`|\[\d+\])/)
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith('`') && part.endsWith('`')) {
          return <code key={i} className="query-inline-code">{part.slice(1, -1)}</code>
        }
        if (/^\[\d+\]$/.test(part)) {
          return <sup key={i} className="query-citation">{part}</sup>
        }
        return <span key={i}>{part}</span>
      })}
    </>
  )
}
