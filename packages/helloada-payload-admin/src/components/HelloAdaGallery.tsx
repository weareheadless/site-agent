'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Image from 'next/image'
import Link from 'next/link'

import { fetchHelloAda } from '../api/fetchHelloAda'
import { useHelloAdaTranslations } from '../api/useHelloAdaTranslations'
import { useHelloAdaSite } from '../config/provider'
import { mediaUrl as migrationMediaUrl } from '../lib/media'
import { HelloAdaMark } from './HelloAdaLogo'
import { WorkspaceIcon } from './WorkspaceIcon'

type GalleryMedia = {
  id: string | number
  url?: string | null
  filename?: string | null
  alt?: string | null
  sourceId?: string | null
  sourceUrl?: string | null
  originalUrl?: string | null
  sourcePages?: string[]
}

type GalleryResponse = {
  media?: GalleryMedia[]
  hasNextPage?: boolean
}

const mediaUrl = (media: GalleryMedia) => {
  const migrated = migrationMediaUrl(media)
  return migrated || String(media.url || media.sourceUrl || media.originalUrl || '').trim()
}

const mediaLabel = (media: GalleryMedia) => media.alt || media.filename || media.sourcePages?.[0] || `Image ${media.id}`

const conversationHref = (media: GalleryMedia) => {
  const params = new URLSearchParams({
    asset_id: String(media.id),
    asset_name: media.filename || media.alt || 'Selected image',
  })
  const source = mediaUrl(media)
  if (source) params.set('asset_url', source)
  return `/admin?${params.toString()}`
}

export function HelloAdaGallery() {
  const { t } = useHelloAdaTranslations()
  const site = useHelloAdaSite()
  const [media, setMedia] = useState<GalleryMedia[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [hasNextPage, setHasNextPage] = useState(false)
  const [page, setPage] = useState(1)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async (nextPage: number, append: boolean, query: string) => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ limit: '72', page: String(nextPage) })
      if (query.trim()) params.set('search', query.trim())
      const response = await fetchHelloAda(`/api/helloada/media-library?${params.toString()}`, { cache: 'no-store' })
      const body = (await response.json()) as GalleryResponse & { message?: string }
      if (!response.ok) throw new Error(body.message || t('error.pageLoad'))
      setMedia((current) => append ? [...current, ...(body.media || []).filter((item) => !current.some((known) => String(known.id) === String(item.id)))] : body.media || [])
      setPage(nextPage)
      setHasNextPage(body.hasNextPage === true)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('error.pageLoad'))
      if (!append) setMedia([])
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    const timer = window.setTimeout(() => void load(1, false, search), search ? 240 : 0)
    return () => window.clearTimeout(timer)
  }, [load, search])

  const upload = async (file: File) => {
    if (!file.type.startsWith('image/') || uploading) return
    setUploading(true)
    setError('')
    try {
      const form = new FormData()
      form.append('file', file)
      const response = await fetchHelloAda('/api/helloada/media/upload', { method: 'POST', body: form })
      const body = (await response.json()) as { attachment?: { asset_id?: string | number; url?: string; preview_url?: string; name?: string; alt_text?: string }; message?: string }
      if (!response.ok || body.attachment?.asset_id === undefined) throw new Error(body.message || t('error.imageAttach'))
      await load(1, false, search)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('error.imageAttach'))
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <main className="helloada-gallery">
      <header className="helloada-gallery-header">
        <div className="helloada-gallery-heading">
          <HelloAdaMark size={42} />
          <div>
            <p className="helloada-eyebrow">{site.siteName}</p>
            <h1>{t('owner.galleryTitle')}</h1>
            <p>{t('owner.galleryIntro')}</p>
          </div>
        </div>
        <div className="helloada-gallery-actions">
          <Link className="helloada-gallery-secondary" href="/admin/collections/media">{t('owner.galleryOpenPayload')}<WorkspaceIcon name="external" size={15} /></Link>
          <button className="helloada-gallery-upload" type="button" onClick={() => inputRef.current?.click()} disabled={uploading}>
            <WorkspaceIcon name="plus" size={15} />{uploading ? t('workspace.attachingImage') : t('workspace.pageUploadImage')}
          </button>
          <input ref={inputRef} className="helloada-file-input" type="file" accept="image/*" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file) }} />
        </div>
      </header>

      <section className="helloada-gallery-shell" aria-label={t('owner.galleryTitle')}>
        <div className="helloada-gallery-toolbar">
          <label>
            <span>{t('workspace.pageGallerySearchLabel')}</span>
            <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('workspace.pageGallerySearchPlaceholder')} />
          </label>
          <span className="helloada-gallery-count">{media.length} {t('owner.galleryCount')}</span>
        </div>
        {error ? <p className="helloada-gallery-message is-error" role="alert">{error}</p> : null}
        {loading && !media.length ? <p className="helloada-gallery-message">{t('workspace.pageGalleryLoading')}</p> : null}
        {!loading && !media.length && !error ? <p className="helloada-gallery-message">{t('workspace.pageGalleryNoMatch')}</p> : null}
        {media.length ? (
          <div className="helloada-gallery-grid">
            {media.map((item) => {
              const source = mediaUrl(item)
              return (
                <article className="helloada-gallery-card" key={String(item.id)}>
                  <div className="helloada-gallery-card-image">
                    {source ? <Image src={source} alt={mediaLabel(item)} width={360} height={250} unoptimized /> : <span>{t('workspace.pageGalleryUnavailable')}</span>}
                  </div>
                  <div className="helloada-gallery-card-meta">
                    <div><strong>{mediaLabel(item)}</strong><small>{item.filename || `#${item.id}`}</small></div>
                    <Link className="helloada-gallery-use" href={conversationHref(item)}>{t('owner.galleryUseInChat')}<WorkspaceIcon name="arrow" size={15} /></Link>
                  </div>
                </article>
              )
            })}
          </div>
        ) : null}
        {hasNextPage ? <button className="helloada-gallery-more" type="button" onClick={() => void load(page + 1, true, search)} disabled={loading}>{loading ? t('workspace.pageGalleryLoading') : t('workspace.pageGalleryMore')}</button> : null}
      </section>
    </main>
  )
}
