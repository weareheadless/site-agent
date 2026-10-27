import Link from 'next/link'
import { helloAdaBindingId } from '@weareheadless/helloada-payload-core/bindings'

import { getPublishedPosts, getSiteSettings, mediaAlt, mediaUrl } from '@/lib/content'

export default async function BlogIndex() {
  const [posts, settings] = await Promise.all([getPublishedPosts(), getSiteSettings()])
  return (
    <main className="content-page">
      {settings.journalTitle ? <h1>{String(settings.journalTitle)}</h1> : null}
      {settings.journalDescription ? <p className="article-intro">{String(settings.journalDescription)}</p> : null}
      <div className="post-grid">
        {posts.map((post) => {
          const image = mediaUrl(post.featuredImage)
          const documentId = String(post.id || '')
          const binding = (field: string) => helloAdaBindingId('posts', documentId, { collection: 'posts', documentId, field })
          return (
            <article key={String(post.id || post.slug)} className="post-card">
              {image ? <img src={image} alt={mediaAlt(post.featuredImage)} data-helloada-field={binding('featuredImage')} /> : null}
              <div>
                {post.publishedAt ? <p className="post-date">{new Date(String(post.publishedAt)).toLocaleDateString()}</p> : null}
                <h2><Link href={`/articles/${encodeURIComponent(String(post.slug))}`} data-helloada-field={binding('title')}>{String(post.title || '')}</Link></h2>
                {post.summary ? <p data-helloada-field={binding('summary')}>{post.summary}</p> : null}
              </div>
            </article>
          )
        })}
      </div>
    </main>
  )
}
