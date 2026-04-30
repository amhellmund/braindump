import { useState, useRef, useEffect } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faChevronDown, faChevronUp, faPlus, faClockRotateLeft } from '@fortawesome/free-solid-svg-icons'
import {
  ChatTurn,
  QuerySource,
  ChatSessionSummary,
  sendQuery,
  fetchChatSessions,
  fetchChatSession,
} from '../api'
import { useErrorToast } from './ErrorToastContext'
import MarkdownPreview from './MarkdownPreview'
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
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historySessions, setHistorySessions] = useState<ChatSessionSummary[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (expanded) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, expanded])

  useEffect(() => {
    if (!historyOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setHistoryOpen(false)
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [historyOpen])

  const submit = async () => {
    if (!query.trim() || loading) return
    const text = query.trim()
    setQuery('')
    setExpanded(true)
    setHistoryOpen(false)

    setMessages(prev => [...prev, { role: 'user' as const, text }])
    setLoading(true)

    try {
      const history: ChatTurn[] = messages.map(m =>
        m.role === 'user'
          ? { role: 'user' as const, text: m.text }
          : { role: 'assistant' as const, text: m.answer }
      )
      const result = await sendQuery(text, history, sessionId ?? undefined)
      setSessionId(result.sessionId)
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
    setSessionId(null)
    setHistoryOpen(false)
  }

  const openHistory = async () => {
    if (historyOpen) {
      setHistoryOpen(false)
      return
    }
    setHistoryOpen(true)
    setHistoryLoading(true)
    try {
      const sessions = await fetchChatSessions()
      setHistorySessions(sessions)
    } catch (err: unknown) {
      pushError('Failed to load chat history', String(err))
    } finally {
      setHistoryLoading(false)
    }
  }

  const loadSession = async (id: string) => {
    try {
      const detail = await fetchChatSession(id)
      const restored: Message[] = detail.turns.flatMap(t => [
        { role: 'user' as const, text: t.query },
        { role: 'assistant' as const, answer: t.answer, sources: t.citations },
      ])
      setMessages(restored)
      setSessionId(id)
      setExpanded(true)
      setHistoryOpen(false)
    } catch (err: unknown) {
      pushError('Failed to load session', String(err))
    }
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
                  <MarkdownPreview raw={msg.answer} stripFrontmatter={false} />
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

      {/* History panel */}
      {historyOpen && (
        <div className="query-history-panel">
          <div className="query-history-header">Recent chats</div>
          {historyLoading ? (
            <div className="query-history-empty">Loading…</div>
          ) : historySessions.length === 0 ? (
            <div className="query-history-empty">No chat history yet.</div>
          ) : (
            <ul className="query-history-list">
              {historySessions.map(s => (
                <li
                  key={s.id}
                  className={`query-history-item${s.id === sessionId ? ' active' : ''}`}
                  onClick={() => loadSession(s.id)}
                >
                  <span className="history-item-title">{s.title}</span>
                  <span className="history-item-meta">{s.turnCount} turn{s.turnCount !== 1 ? 's' : ''}</span>
                </li>
              ))}
            </ul>
          )}
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
        <button
          className={`query-icon-btn${historyOpen ? ' active' : ''}`}
          onClick={openHistory}
          title="Chat history"
        >
          <FontAwesomeIcon icon={faClockRotateLeft} />
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
