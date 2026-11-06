'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchHelloAda } from '../api/fetchHelloAda'
import { useHelloAdaTranslations } from '../api/useHelloAdaTranslations'
import { responseMessage } from '../api/response-message'
import { WorkspaceIcon } from './WorkspaceIcon'

type Checkpoint = {
  sha: string
  shortSha: string
  message: string
  author: string
  date: string
  isLive: boolean
  published: boolean
  summary: string
  label: string
  publishedTs: string
  versionType: string
  canRestore: boolean
}

type CheckpointIndex = {
  checkpoints: Checkpoint[]
  liveSha: string
  live: { sha: string; releaseId: string; fingerprint: string }
  reviewPending: boolean
  reviewDraftId: number | null
  reviewTitle: string
}

const relative = (value: string, language: string) => {
  const parsed = Date.parse(value)
  if (Number.isNaN(parsed)) return ''
  const minutes = Math.round((parsed - Date.now()) / 60_000)
  const formatter = new Intl.RelativeTimeFormat(language, { numeric: 'auto' })
  if (Math.abs(minutes) < 60) return formatter.format(minutes, 'minute')
  const hours = Math.round(minutes / 60)
  if (Math.abs(hours) < 24) return formatter.format(hours, 'hour')
  const days = Math.round(hours / 24)
  if (Math.abs(days) < 30) return formatter.format(days, 'day')
  return formatter.format(Math.round(days / 30), 'month')
}

/** The site's own Git history, as restorable checkpoints. */
export function CheckpointHistory({
  open,
  onClose,
  onRestored,
}: {
  open: boolean
  onClose: () => void
  onRestored?: (draftId: number) => void
}) {
  const { language, t } = useHelloAdaTranslations()
  const [data, setData] = useState<CheckpointIndex>()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [busySha, setBusySha] = useState('')
  const [confirming, setConfirming] = useState('')
  const dialogRef = useRef<HTMLDialogElement>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const response = await fetchHelloAda('/api/helloada/checkpoints?limit=25', { cache: 'no-store' })
      const body = (await response.json()) as CheckpointIndex & { message?: string }
      if (!response.ok) throw new Error(responseMessage(body, t('checkpoints.unavailable')))
      setData(body)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('checkpoints.unavailable'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  useEffect(() => {
    if (!open) return
    const timer = window.setTimeout(() => { void load() }, 0)
    return () => window.clearTimeout(timer)
  }, [load, open])

  const restore = async (checkpoint: Checkpoint) => {
    if (busySha) return
    setBusySha(checkpoint.sha)
    setError('')
    try {
      const response = await fetchHelloAda('/api/helloada/checkpoints/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ commit: checkpoint.sha, summary: checkpoint.label || checkpoint.message }),
      })
      const body = (await response.json()) as { draft_id?: number; message?: string }
      if (!response.ok) throw new Error(responseMessage(body, t('checkpoints.restoreFailed')))
      setConfirming('')
      if (body.draft_id) onRestored?.(body.draft_id)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('checkpoints.restoreFailed'))
    } finally {
      setBusySha('')
    }
  }

  const live = data?.checkpoints.find((checkpoint) => checkpoint.isLive)
  const rows = data?.checkpoints || []

  return (
    <dialog
      ref={dialogRef}
      className="helloada-checkpoints-drawer"
      aria-labelledby="helloada-checkpoints-title"
      onClose={() => {
        setConfirming('')
        setError('')
        onClose()
      }}
      onClick={(event) => { if (event.target === event.currentTarget) dialogRef.current?.close() }}
    >
      <header className="helloada-checkpoints-head">
        <div>
          <p className="helloada-title-kicker">{t('checkpoints.kicker')}</p>
          <h2 id="helloada-checkpoints-title">{t('checkpoints.title')}</h2>
        </div>
        <button className="helloada-checkpoints-close" type="button" onClick={() => dialogRef.current?.close()} aria-label={t('checkpoints.close')}>
          <WorkspaceIcon name="close" size={16} />
        </button>
      </header>

      <div className="helloada-checkpoints-scroll">
        <section className="helloada-live-card" aria-label={t('checkpoints.liveNow')}>
          <p className="helloada-title-kicker">{t('checkpoints.liveNow')}</p>
          {live ? (
            <>
              <strong>{live.label || live.message}</strong>
              <p className="helloada-checkpoint-meta">
                <code>{live.shortSha}</code>
                <span>·</span>
                <span>{relative(live.date, language)}</span>
              </p>
            </>
          ) : data?.live.sha ? (
            <>
              <strong>{t('checkpoints.liveUnlisted')}</strong>
              <p className="helloada-checkpoint-meta"><code>{data.live.sha.slice(0, 7)}</code></p>
            </>
          ) : (
            <p className="helloada-checkpoints-empty">{t('checkpoints.noLive')}</p>
          )}
        </section>

        {error ? <div className="helloada-alert" role="alert">{error}</div> : null}
        {data?.reviewPending ? (
          <p className="helloada-drawer-note" role="status">
            {t('checkpoints.reviewPending')}
            {data.reviewDraftId ? <em> · #{data.reviewDraftId}</em> : null}
          </p>
        ) : null}

        <div className="helloada-checkpoint-heading">
          <span>{t('checkpoints.all')}</span>
          <span>{rows.length}</span>
        </div>

        {loading && !rows.length ? (
          <p className="helloada-checkpoints-empty">{t('checkpoints.loading')}</p>
        ) : rows.length ? (
          <ol className="helloada-checkpoint-list">
            {rows.map((checkpoint) => {
              const isConfirming = confirming === checkpoint.sha
              const disabled = Boolean(busySha) || Boolean(data?.reviewPending) || !checkpoint.canRestore
              return (
                <li key={checkpoint.sha} className={`helloada-checkpoint ${checkpoint.isLive ? 'is-live' : ''} ${isConfirming ? 'is-confirming' : ''}`}>
                  <span className="helloada-checkpoint-rail" aria-hidden="true"><i /></span>
                  <div className="helloada-checkpoint-body">
                    <p className="helloada-checkpoint-title">{checkpoint.label || checkpoint.message}</p>
                    <p className="helloada-checkpoint-meta">
                      <code>{checkpoint.shortSha}</code>
                      <span>·</span>
                      <span>{relative(checkpoint.date, language)}</span>
                      {checkpoint.isLive ? (
                        <span className="helloada-checkpoint-badge is-live">{t('checkpoints.badgeLive')}</span>
                      ) : checkpoint.published ? (
                        <span className="helloada-checkpoint-badge">{t('checkpoints.badgePublished')}</span>
                      ) : (
                        <span className="helloada-checkpoint-badge is-quiet">{t('checkpoints.badgeUnreleased')}</span>
                      )}
                    </p>
                    {isConfirming ? (
                      <div className="helloada-checkpoint-confirm" role="group" aria-label={t('checkpoints.confirmTitle')}>
                        <p>{t('checkpoints.confirmBody')}</p>
                        <div>
                          <button type="button" className="is-primary" disabled={Boolean(busySha)} onClick={() => void restore(checkpoint)}>
                            {busySha === checkpoint.sha ? t('checkpoints.preparing') : t('checkpoints.confirm')}
                          </button>
                          <button type="button" className="is-quiet" disabled={Boolean(busySha)} onClick={() => setConfirming('')}>
                            {t('checkpoints.cancel')}
                          </button>
                        </div>
                      </div>
                    ) : checkpoint.canRestore ? (
                      <button
                        className="helloada-checkpoint-action"
                        type="button"
                        disabled={disabled}
                        title={data?.reviewPending ? t('checkpoints.reviewPendingShort') : undefined}
                        onClick={() => setConfirming(checkpoint.sha)}
                      >
                        {t('checkpoints.restore')}
                      </button>
                    ) : null}
                  </div>
                </li>
              )
            })}
          </ol>
        ) : (
          <p className="helloada-checkpoints-empty">{t('checkpoints.empty')}</p>
        )}
      </div>

      <footer className="helloada-checkpoints-foot">
        <p>{t('checkpoints.note')}</p>
        <button type="button" onClick={() => void load()} disabled={loading}>
          <WorkspaceIcon name="refresh" size={13} />
          {t('checkpoints.refresh')}
        </button>
      </footer>
    </dialog>
  )
}
