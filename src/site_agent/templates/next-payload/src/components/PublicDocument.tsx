import { lexicalParagraphs, mediaAlt, mediaUrl } from '@/lib/content'

type Document = Record<string, any>

export default function PublicDocument({ document, settings, kind }: {
  document?: Document
  settings: Document
  kind: 'page' | 'post'
}) {
  const image = mediaUrl(document?.featuredImage)
  const paragraphs = lexicalParagraphs(document?.body)
  if (kind === 'post') {
    return (
      <main className="content-page article-page">
        <a href="/articles">← All articles</a>
        <p className="eyebrow">{document?.category || 'Journal'}</p>
        <h1>{document?.title || 'Untitled article'}</h1>
        {image ? <img className="article-image" src={image} alt={mediaAlt(document?.featuredImage)} /> : null}
        {document?.summary ? <p className="article-intro">{document.summary}</p> : null}
        <div className="article-body">
          {paragraphs.map((paragraph: string, index: number) => <p key={`${index}-${paragraph.slice(0, 12)}`}>{paragraph}</p>)}
        </div>
        <small>{settings.siteName || 'Website'} · {document?.publishedAt ? new Date(String(document.publishedAt)).toLocaleDateString() : 'Draft article'}</small>
      </main>
    )
  }
  return (
    <main className="content-page">
      <p className="eyebrow">{settings.siteName || 'HelloAda site'}</p>
      <h1>{document?.title || settings.siteName || 'Your new website'}</h1>
      {image ? <img className="article-image" src={image} alt={mediaAlt(document?.featuredImage)} /> : null}
      {document?.summary ? <p className="article-intro">{document.summary}</p> : null}
      <div className="article-body">
        {paragraphs.map((paragraph: string, index: number) => <p key={`${index}-${paragraph.slice(0, 12)}`}>{paragraph}</p>)}
      </div>
      {!document ? <p className="empty-state">This homepage is ready for its first owner-approved content update in Payload.</p> : null}
    </main>
  )
}
