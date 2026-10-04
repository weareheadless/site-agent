import Link from 'next/link'
import { RichText } from '@payloadcms/richtext-lexical/react'
import type { SerializedEditorState } from 'lexical'
import { helloAdaBindingId } from '@weareheadless/helloada-payload-core/bindings'
import { mediaAlt, mediaUrl } from '@/lib/content'
import TenantSections from '@/components/site/TenantSections'
import { articleIndexPath } from '@/lib/content-routes'

type RecordValue = Record<string, unknown>

const objectValue = (value: unknown): RecordValue =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as RecordValue : {}

export default function PagePresentation({ document, settings, kind, collection }: {
  document: RecordValue
  settings: RecordValue
  kind: 'page' | 'post' | 'product'
  collection: 'pages' | 'posts' | 'products'
}) {
  const documentId = String(document.id || '')
  if (!documentId) throw new Error('Public Payload content has no stable document ID.')
  const title = String(document.title || '').trim()
  if (!title) throw new Error(`Published ${collection} document has no title.`)
  const image = mediaUrl(document.featuredImage)
  const sections = Array.isArray(document.sections) ? document.sections as RecordValue[] : []
  const category = objectValue(document.category)
  const bind = (field: string) => helloAdaBindingId(collection, documentId, { collection, documentId, field })
  if (document.featuredImage && !image) throw new Error('The selected Payload image has no public URL.')

  return <main className={`content-page${kind === 'post' ? ' article-page' : kind === 'product' ? ' product-page' : ''}`}
    data-helloada-document-id={documentId} data-helloada-updated-at={String(document.updatedAt || '')}>
    {kind === 'post' ? <Link href={articleIndexPath()} aria-label="Back to journal">← {String(settings.journalTitle || '').trim()}</Link> : null}
    {kind === 'post' && document.category ? <p className="eyebrow">{String(category.title || '').trim()}</p> : null}
    <h1 data-helloada-field={bind('title')}>{title}</h1>
    {image ? <img className="article-image" src={image} alt={mediaAlt(document.featuredImage)} data-helloada-field={bind('featuredImage')} /> : null}
    {document.summary ? <p className="article-intro" data-helloada-field={bind('summary')}>{String(document.summary)}</p> : null}
    {document.body ? <div className="article-body" data-helloada-field={bind('body')}><RichText data={document.body as SerializedEditorState} /></div> : null}
    <TenantSections sections={sections} collection={collection} documentId={documentId} />
    {kind === 'post' && document.publishedAt ? <small>{new Date(String(document.publishedAt)).toLocaleDateString()}</small> : null}
  </main>
}
