import Link from 'next/link'

import { getPublishedPosts, mediaAlt, mediaUrl } from '@/lib/content'

export default async function BlogIndex() {
  const posts = await getPublishedPosts()
  return (
    <main className="content-page">
      <p className="eyebrow">Journal</p>
      <h1>Ideas, updates, and useful things to know.</h1>
      <div className="post-grid">
        {posts.map((post) => {
          const image = mediaUrl(post.featuredImage)
          return (
            <article key={String(post.id || post.slug)} className="post-card">
              {image ? <img src={image} alt={mediaAlt(post.featuredImage)} /> : null}
              <div>
                <p className="post-date">{post.publishedAt ? new Date(String(post.publishedAt)).toLocaleDateString() : 'Journal'}</p>
                <h2><Link href={`/articles/${post.slug}`}>{post.title}</Link></h2>
                {post.summary ? <p>{post.summary}</p> : null}
              </div>
            </article>
          )
        })}
      </div>
      {!posts.length ? <p className="empty-state">Your published articles will appear here once they are added in Payload.</p> : null}
    </main>
  )
}
