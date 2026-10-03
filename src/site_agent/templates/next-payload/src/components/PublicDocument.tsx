import { RichText } from '@payloadcms/richtext-lexical/react'
import { helloAdaBindingId } from '@weareheadless/helloada-payload-core/bindings'
import { mediaAlt, mediaUrl } from '@/lib/content'
import TenantSections from '@/components/site/TenantSections'

type RecordValue = Record<string, any>
export default function PublicDocument({ document, settings, kind }: {
  document?: RecordValue
  settings: RecordValue
  kind: 'page' | 'post'
}) {
  if (!document) return null
  const image = mediaUrl(document.featuredImage)
  const sections = Array.isArray(document.sections) ? document.sections as RecordValue[] : []
  const collection = kind === 'post' ? 'posts' : 'pages'
  const documentId = String(document.id || '')
  return (
    <main className={`content-page${kind === 'post' ? ' article-page' : ''}`}>
      {kind === 'post' ? <a href="/articles">← {String(settings.journalTitle || 'Articles')}</a> : null}
      {kind === 'post' && document.category ? <p className="eyebrow">{String(document.category.title || document.category)}</p> : null}
      <h1 data-helloada-field={helloAdaBindingId(collection, documentId, { collection, documentId, field: 'title' })}>{String(document.title || '')}</h1>
      {image ? <img className="article-image" src={image} alt={mediaAlt(document.featuredImage)}
        data-helloada-field={helloAdaBindingId(collection, documentId, { collection, documentId, field: 'featuredImage' })} /> : null}
      {document.summary ? <p className="article-intro" data-helloada-field={helloAdaBindingId(collection, documentId, { collection, documentId, field: 'summary' })}>{String(document.summary)}</p> : null}
      {document.body ? <div className="article-body" data-helloada-field={helloAdaBindingId(collection, documentId, { collection, documentId, field: 'body' })}>
        <RichText data={document.body} />
      </div> : null}
      <TenantSections sections={sections} collection={collection} documentId={documentId} />
      {kind === 'post' ? <small>{String(settings.siteName || '')} · {document.publishedAt ? new Date(String(document.publishedAt)).toLocaleDateString() : ''}</small> : null}
    </main>
  )
}
