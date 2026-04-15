import { Fragment } from 'react'
import './MarkdownPreview.css'

interface Props {
  raw: string
  stripFrontmatter?: boolean
}

// Renders inline markdown: `code`, **bold**, *italic*, [link](url)
function renderInline(text: string): React.ReactNode {
  // Pattern: inline code, bold, italic, links, footnote refs — in priority order
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\)|\[\d+\])/g
  const parts: React.ReactNode[] = []
  let last = 0
  let match: RegExpExecArray | null

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) {
      parts.push(text.slice(last, match.index))
    }
    const token = match[0]
    if (token.startsWith('`')) {
      parts.push(<code key={match.index} className="md-inline-code">{token.slice(1, -1)}</code>)
    } else if (token.startsWith('**')) {
      parts.push(<strong key={match.index}>{token.slice(2, -2)}</strong>)
    } else if (token.startsWith('*')) {
      parts.push(<em key={match.index}>{token.slice(1, -1)}</em>)
    } else if (/^\[\d+\]$/.test(token)) {
      parts.push(<sup key={match.index} className="md-footnote-ref">{token}</sup>)
    } else {
      // link: [label](url)
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
      if (linkMatch) {
        parts.push(
          <a key={match.index} href={linkMatch[2]} className="md-link" target="_blank" rel="noreferrer">
            {linkMatch[1]}
          </a>
        )
      } else {
        parts.push(token)
      }
    }
    last = match.index + token.length
  }

  if (last < text.length) {
    parts.push(text.slice(last))
  }

  return parts.length === 1 ? parts[0] : <Fragment>{parts}</Fragment>
}

export default function MarkdownPreview({ raw, stripFrontmatter = true }: Props) {
  const body = stripFrontmatter ? raw.replace(/^---[\s\S]*?---\n/, '') : raw
  const lines = body.split('\n')
  const elements: React.ReactNode[] = []
  let key = 0
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Fenced code block — collect until closing ```
    if (line.startsWith('```')) {
      const lang = line.slice(3).trim() || undefined
      const codeLines: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i])
        i++
      }
      i++ // consume closing ```
      elements.push(
        <pre key={key++} className="md-code-block">
          {lang && <span className="md-code-lang">{lang}</span>}
          <code>{codeLines.join('\n')}</code>
        </pre>
      )
      continue
    }

    // Unordered list — collect consecutive `- ` or `* ` lines
    if (/^[*-] /.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^[*-] /.test(lines[i])) {
        items.push(lines[i].slice(2))
        i++
      }
      elements.push(
        <ul key={key++} className="md-list">
          {items.map((item, idx) => (
            <li key={idx}>{renderInline(item)}</li>
          ))}
        </ul>
      )
      continue
    }

    // Ordered list — collect consecutive `N. ` lines
    if (/^\d+\. /.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\d+\. /.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\. /, ''))
        i++
      }
      elements.push(
        <ol key={key++} className="md-list">
          {items.map((item, idx) => (
            <li key={idx}>{renderInline(item)}</li>
          ))}
        </ol>
      )
      continue
    }

    if (line.startsWith('### ')) {
      elements.push(<h3 key={key++}>{renderInline(line.slice(4))}</h3>)
    } else if (line.startsWith('## ')) {
      elements.push(<h2 key={key++}>{renderInline(line.slice(3))}</h2>)
    } else if (line.startsWith('# ')) {
      elements.push(<h1 key={key++}>{renderInline(line.slice(2))}</h1>)
    } else if (line.trim() === '') {
      elements.push(<div key={key++} className="md-spacer" />)
    } else {
      const imgMatch = line.match(/^!\[([^\]]*)\]\(([^)]+)\)$/)
      if (imgMatch) {
        const [, alt, src] = imgMatch
        elements.push(<img key={key++} src={src} alt={alt} className="md-image" />)
      } else {
        elements.push(<p key={key++}>{renderInline(line)}</p>)
      }
    }
    i++
  }

  return <div className="md-preview">{elements}</div>
}
