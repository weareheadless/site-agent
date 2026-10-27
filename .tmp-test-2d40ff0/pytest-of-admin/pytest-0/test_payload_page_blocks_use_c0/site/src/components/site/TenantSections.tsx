import { RichText } from '@payloadcms/richtext-lexical/react'
import { helloAdaBindingId } from '@weareheadless/helloada-payload-core/bindings'
import { mediaAlt, mediaUrl } from '@/lib/content'

type ContentEntry = Record<string, any> & { key: string; blockType: string }
type Section = Record<string, any> & { key: string; label: string }

const requiredText = (value: unknown, field: string) => {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`Payload content is missing required ${field}.`)
  return value
}

const stableKey = (value: unknown, field: string) => requiredText(value, `${field} ID`)

const safeHref = (value: unknown) => {
  const href = requiredText(value, 'link destination').trim()
  if (href.startsWith('//') || href.includes('\\') || [...href].some((char) => char.charCodeAt(0) < 32)) {
    throw new Error('Payload contains an unsafe link destination.')
  }
  if (href.startsWith('/') || href.startsWith('#') || href.startsWith('mailto:') || href.startsWith('tel:')) return href
  try {
    const url = new URL(href)
    if (url.protocol === 'https:' || url.protocol === 'http:') return href
  } catch {
    // An invalid URL is a schema violation, not an optional link.
  }
  throw new Error('Payload contains an unsupported link destination.')
}

const requiredMediaUrl = (value: unknown) => {
  const url = mediaUrl(value)
  if (!url) throw new Error('A selected Payload image has no public media URL.')
  return url
}

function ContentEntryView({ entry, collection, documentId, sectionKey }: {
  entry: ContentEntry
  collection: string
  documentId: string
  sectionKey: string
}) {
  const key = stableKey(entry.key, 'Content')
  const target = { collection, documentId, sectionKey, entryKey: key }
  switch (entry.blockType) {
    case 'helloAdaHeading': {
      const text = requiredText(entry.text, 'heading')
      const level = entry.level
      const marker = helloAdaBindingId(collection, documentId, { ...target, field: 'entry', property: 'text' })
      if (level === 'h3') return <h3 className="content-heading" data-content-key={key} data-helloada-field={marker}>{text}</h3>
      if (level === 'h4') return <h4 className="content-heading" data-content-key={key} data-helloada-field={marker}>{text}</h4>
      if (level === 'h2' || level === undefined) return <h2 className="content-heading" data-content-key={key} data-helloada-field={marker}>{text}</h2>
      throw new Error(`Payload heading “${key}” has an unsupported level.`)
    }
    case 'helloAdaParagraph':
      return <p className="content-paragraph" data-content-key={key}
        data-helloada-field={helloAdaBindingId(collection, documentId, { ...target, field: 'entry', property: 'text' })}>{requiredText(entry.text, 'paragraph')}</p>
    case 'helloAdaRichText': {
      const value = entry.value
      if (!value) throw new Error(`Payload rich-text item “${key}” has no content.`)
      return <div className="content-rich-text" data-content-key={key}
        data-helloada-field={helloAdaBindingId(collection, documentId, { ...target, field: 'entry', property: 'value' })}>
        <RichText data={value} />
      </div>
    }
    case 'helloAdaImage':
      return <figure className="content-image" data-content-key={key}
        data-helloada-field={helloAdaBindingId(collection, documentId, { ...target, field: 'entry', property: 'image' })}>
        <img src={requiredMediaUrl(entry.image)} alt={String(entry.alt || mediaAlt(entry.image))} />
        {entry.caption ? <figcaption>{entry.caption}</figcaption> : null}
      </figure>
    case 'helloAdaLink': {
      const text = requiredText(entry.text, 'link text')
      const href = safeHref(entry.href)
      return <a className="content-link" data-content-key={key}
        data-helloada-field={helloAdaBindingId(collection, documentId, { ...target, field: 'entry', property: 'text' })} href={href}
        target={entry.newTab ? '_blank' : undefined} rel={entry.newTab ? 'noreferrer' : undefined}>{text}</a>
    }
    case 'helloAdaContentList': {
      if (!Array.isArray(entry.items)) throw new Error(`Payload list “${key}” has invalid items.`)
      return <ul className="content-list" data-content-key={key}>
        {entry.items.map((item: Record<string, any>) => {
          const itemKey = stableKey(item.key, 'List item')
          const src = item.image ? requiredMediaUrl(item.image) : ''
          const href = item.href ? safeHref(item.href) : ''
          if (href && !item.linkText) throw new Error(`Payload list item “${itemKey}” has a destination but no link text.`)
          const itemTarget = { ...target, entryKey: key, itemKey, field: 'item' }
          return <li key={itemKey} data-content-key={itemKey}>
            {src ? <img src={src} alt={String(item.alt || mediaAlt(item.image))}
              data-helloada-field={helloAdaBindingId(collection, documentId, { ...itemTarget, property: 'image' })} /> : null}
            {item.title ? <h3 data-helloada-field={helloAdaBindingId(collection, documentId, { ...itemTarget, property: 'title' })}>{item.title}</h3> : null}
            {item.body ? <p data-helloada-field={helloAdaBindingId(collection, documentId, { ...itemTarget, property: 'body' })}>{item.body}</p> : null}
            {href ? <a href={href} data-helloada-field={helloAdaBindingId(collection, documentId, { ...itemTarget, property: 'linkText' })}>{item.linkText}</a> : null}
          </li>
        })}
      </ul>
    }
    default:
      throw new Error(`Payload content “${key}” uses unsupported block type “${entry.blockType}”.`)
  }
}

export default function TenantSections({ sections, collection, documentId }: {
  sections: Record<string, any>[]
  collection: string
  documentId: string
}) {
  return <>
    {sections.map((section: Section) => {
      const sectionKey = stableKey(section.key, 'Section')
      const label = requiredText(section.label, `Section “${sectionKey}” name`)
      const sectionBinding = helloAdaBindingId(collection, documentId, { collection, documentId, sectionKey, field: 'sectionLabel' })
      const entries = section.entries === undefined ? [] : section.entries
      if (!Array.isArray(entries)) throw new Error(`Payload section “${sectionKey}” content is invalid.`)
      return <section className="content-section" key={sectionKey} data-section-key={sectionKey}>
        <h2 data-helloada-field={sectionBinding}>{label}</h2>
        {entries.map((entry: ContentEntry) => <ContentEntryView key={stableKey(entry.key, 'Content')} entry={entry} collection={collection} documentId={documentId} sectionKey={sectionKey} />)}
      </section>
    })}
  </>
}
