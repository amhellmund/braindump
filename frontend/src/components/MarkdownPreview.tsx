import './MarkdownPreview.css'

interface Props {
  raw: string
  stripFrontmatter?: boolean
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

    if (line.startsWith('### ')) {
      elements.push(<h3 key={key++}>{line.slice(4)}</h3>)
    } else if (line.startsWith('## ')) {
      elements.push(<h2 key={key++}>{line.slice(3)}</h2>)
    } else if (line.startsWith('# ')) {
      elements.push(<h1 key={key++}>{line.slice(2)}</h1>)
    } else if (line.trim() === '') {
      elements.push(<div key={key++} className="md-spacer" />)
    } else {
      const imgMatch = line.match(/^!\[([^\]]*)\]\(([^)]+)\)$/)
      if (imgMatch) {
        const [, alt, src] = imgMatch
        elements.push(<img key={key++} src={src} alt={alt} className="md-image" />)
      } else {
        elements.push(<p key={key++}>{line}</p>)
      }
    }
    i++
  }

  return <div className="md-preview">{elements}</div>
}
