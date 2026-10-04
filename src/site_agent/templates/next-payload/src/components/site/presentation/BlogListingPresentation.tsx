import Link from 'next/link'
import { helloAdaBindingId, helloAdaGlobalBindingId } from '@weareheadless/helloada-payload-core/bindings'
import { mediaAlt, mediaUrl } from '@/lib/content'

type RecordValue = Record<string, unknown>

export default function BlogListingPresentation({ posts, settings, detailBasePath }: {
  posts: RecordValue[]
  settings: RecordValue
  detailBasePath: string
}) {
  return <main className="content-page">
    {settings.journalTitle ? <h1 data-helloada-field={helloAdaGlobalBindingId('siteSettings', 'siteSettings', 'journalTitle')}>{String(settings.journalTitle)}</h1> : null}
    {settings.journalDescription ? <p className="article-intro" data-helloada-field={helloAdaGlobalBindingId('siteSettings', 'siteSettings', 'journalDescription')}>{String(settings.journalDescription)}</p> : null}
    <div className="post-grid">
      {posts.map((post) => {
        const id = String(post.id || '')
        if (!id) throw new Error('Published article has no stable Payload ID.')
        const bind = (field: string) => helloAdaBindingId('posts', id, { collection: 'posts', documentId: id, field })
        const image = mediaUrl(post.featuredImage)
        if (post.featuredImage && !image) throw new Error(`Article “${post.slug}” has no public cover-image URL.`)
        return <article key={id} className="post-card" data-helloada-document-id={id} data-helloada-updated-at={String(post.updatedAt || '')}>
          {image ? <img src={image} alt={mediaAlt(post.featuredImage)} data-helloada-field={bind('featuredImage')} /> : null}
          <div>
            {post.publishedAt ? <p className="post-date">{new Date(String(post.publishedAt)).toLocaleDateString()}</p> : null}
            <h2><Link href={detailBasePath.replace(/\/$/, '') + '/' + String(post.slug).split('/').map(encodeURIComponent).join('/')} data-helloada-field={bind('title')}>{String(post.title || '')}</Link></h2>
            {post.summary ? <p data-helloada-field={bind('summary')}>{String(post.summary)}</p> : null}
          </div>
        </article>
      })}
    </div>
  </main>
}
