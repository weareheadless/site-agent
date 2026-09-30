import type { ReactNode } from 'react'

type InlineMatch = RegExpMatchArray & {
  2?: string
  3?: string
  4?: string
  5?: string
  6?: string
  7?: string
  8?: string
}

const inlinePattern = /(\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)|\*([^*]+)\*|_([^_]+)_)/g

const safeHref = (value: string) => {
  const href = value.trim()
  if (href.startsWith('/') && !href.startsWith('//')) return href
  if (href.startsWith('#')) return href
  try {
    const parsed = new URL(href)
    return ['http:', 'https:', 'mailto:'].includes(parsed.protocol) ? href : undefined
  } catch {
    return undefined
  }
}

const inlineContent = (text: string): ReactNode[] => {
  const nodes: ReactNode[] = []
  let cursor = 0

  for (const match of text.matchAll(inlinePattern)) {
    const start = match.index ?? 0
    if (start > cursor) nodes.push(text.slice(cursor, start))

    const item = match as InlineMatch
    if (item[2] || item[3]) {
      nodes.push(<strong key={`strong-${start}`}>{item[2] || item[3]}</strong>)
    } else if (item[4]) {
      nodes.push(<code key={`code-${start}`}>{item[4]}</code>)
    } else if (item[5] && item[6]) {
      const href = safeHref(item[6])
      nodes.push(
        href ? (
          <a
            key={`link-${start}`}
            href={href}
            rel={href.startsWith('http') ? 'noreferrer' : undefined}
            target={href.startsWith('http') ? '_blank' : undefined}
          >
            {item[5]}
          </a>
        ) : (
          item[5]
        ),
      )
    } else if (item[7] || item[8]) {
      nodes.push(<em key={`em-${start}`}>{item[7] || item[8]}</em>)
    } else {
      nodes.push(match[0])
    }
    cursor = start + match[0].length
  }

  if (cursor < text.length) nodes.push(text.slice(cursor))
  return nodes
}

const inlineLines = (lines: string[]) =>
  lines.flatMap((line, index) => [
    ...(index ? [<br key={`break-${index}`} />] : []),
    ...inlineContent(line),
  ])

export function HelloAdaChatMessage({ text }: { text: string }) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) {
      index += 1
      continue
    }

    if (line.trim().startsWith('```')) {
      const codeLines: string[] = []
      index += 1
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        codeLines.push(lines[index])
        index += 1
      }
      if (index < lines.length) index += 1
      blocks.push(
        <pre key={`code-block-${index}`}>
          <code>{codeLines.join('\n')}</code>
        </pre>,
      )
      continue
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    if (heading) {
      const level = heading[1].length
      const content = inlineContent(heading[2])
      if (level === 1) blocks.push(<h3 key={`heading-${index}`}>{content}</h3>)
      else if (level === 2) blocks.push(<h4 key={`heading-${index}`}>{content}</h4>)
      else blocks.push(<h5 key={`heading-${index}`}>{content}</h5>)
      index += 1
      continue
    }

    const unordered = line.match(/^\s*[-*]\s+(.+)$/)
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/)
    if (unordered || ordered) {
      const items: string[] = []
      const orderedList = Boolean(ordered)
      while (index < lines.length) {
        const item = lines[index].match(orderedList ? /^\s*\d+[.)]\s+(.+)$/ : /^\s*[-*]\s+(.+)$/)
        if (!item) break
        items.push(item[1])
        index += 1
      }
      const List = orderedList ? 'ol' : 'ul'
      blocks.push(
        <List key={`list-${index}`}>
          {items.map((item, itemIndex) => <li key={`${index}-${itemIndex}`}>{inlineContent(item)}</li>)}
        </List>,
      )
      continue
    }

    const quote = line.match(/^\s*>\s?(.*)$/)
    if (quote) {
      const quoteLines: string[] = []
      while (index < lines.length) {
        const item = lines[index].match(/^\s*>\s?(.*)$/)
        if (!item) break
        quoteLines.push(item[1])
        index += 1
      }
      blocks.push(<blockquote key={`quote-${index}`}>{inlineLines(quoteLines)}</blockquote>)
      continue
    }

    const paragraph: string[] = []
    while (index < lines.length && lines[index].trim()) {
      const candidate = lines[index]
      if (
        paragraph.length > 0 &&
        (/^(#{1,3})\s+/.test(candidate) || /^\s*[-*]\s+/.test(candidate) || /^\s*\d+[.)]\s+/.test(candidate) || /^\s*>\s?/.test(candidate) || candidate.trim().startsWith('```'))
      ) {
        break
      }
      paragraph.push(candidate)
      index += 1
    }
    blocks.push(<p key={`paragraph-${index}`}>{inlineLines(paragraph)}</p>)
  }

  return <div className="helloada-chat-message-body">{blocks}</div>
}
