'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { fetchHelloAda } from '../api/fetchHelloAda'
import { useHelloAdaTranslations } from '../api/useHelloAdaTranslations'
import { responseMessage } from '../api/response-message'
import { WorkspaceIcon } from './WorkspaceIcon'

type Release = {
  id: string
  commit: string
  draftId?: number | null
  status: string
  stage: string
  phase: string
  phaseLabel: string
  step: string
  progress: number
  complete: boolean
  failed: boolean
  startedAt: string
  finishedAt: string
  error: string
  live: boolean
}

type PublicationSnapshot = {
  release: Release | null
  live: { sha: string; releaseId: string; fingerprint: string; activated: boolean }
  steps: Array<{ phase: string; label: string }>
  latestPublish: { summary: string; ts: string; commit: string; versionType: string } | null
}

const PHASES = ['queued', 'preparing', 'building', 'uploading', 'going_live', 'verifying'] as const

const elapsedLabel = (from: string, to: number) => {
  const started = Date.parse(from)
  if (Number.isNaN(started)) return ''
  const seconds = Math.max(0, Math.round((to - started) / 1000))
  const minutes = Math.floor(seconds / 60)
  return minutes > 0 ? `${minutes}m ${String(seconds % 60).padStart(2, '0')}s` : `${seconds}s`
}

/** The live publication state of the owner's approved change. */
export function PublicationProgress({
  refreshKey,
  onAskAda,
}: {
  refreshKey: number
  onAskAda?: () => void
}) {
  const { t } = useHelloAdaTranslations()
  const [snapshot, setSnapshot] = useState<PublicationSnapshot>()
  const [error, setError] = useState('')
  const [dismissed, setDismissed] = useState('')
  const [now, setNow] = useState(() => Date.now())
  const requestRef = useRef(0)

  const load = useCallback(async () => {
    const request = ++requestRef.current
    try {
      const response = await fetchHelloAda('/api/helloada/publication', { cache: 'no-store' })
      const body = (await response.json()) as PublicationSnapshot & { message?: string }
      if (!response.ok) throw new Error(responseMessage(body, t('release.unavailable')))
      if (request !== requestRef.current) return
      setSnapshot(body)
      setError('')
    } catch (cause) {
      if (request !== requestRef.current) return
      setError(cause instanceof Error ? cause.message : t('release.unavailable'))
    }
  }, [t])

  useEffect(() => {
    const timer = window.setTimeout(() => { void load() }, 0)
    return () => window.clearTimeout(timer)
  }, [load, refreshKey])

  const release = snapshot?.release
  const running = Boolean(release && !release.complete)

  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => { void load() }, 4_000)
    return () => window.clearInterval(timer)
  }, [load, running])

  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => setNow(Date.now()), 1_000)
    return () => window.clearInterval(timer)
  }, [running])

  const title = useMemo(() => {
    if (!release) return ''
    if (release.failed) return t('release.failedTitle')
    if (release.complete) return t('release.liveTitle')
    return t('release.title')
  }, [release, t])

  const phaseLabel = (phase: string) => {
    const key = `release.phase.${phase}`
    const translated = t(key)
    return translated === key ? phase.replace(/_/g, ' ') : translated
  }

  if (error && !release) {
    return (
      <div className="helloada-release is-failed" role="status">
        <div className="helloada-release-head">
          <div className="helloada-release-copy">
            <strong>{t('release.unavailable')}</strong>
            <span>{error}</span>
          </div>
          <div className="helloada-release-meta">
            <button type="button" onClick={() => void load()}>{t('release.checkAgain')}</button>
          </div>
        </div>
      </div>
    )
  }

  if (!release) return null
  if (dismissed === `${release.id}:${release.startedAt}`) return null

  const finished = release.finishedAt || release.startedAt
  const ageMinutes = (now - Date.parse(finished || release.startedAt || new Date(0).toISOString())) / 60_000
  const recent = Number.isNaN(ageMinutes) || ageMinutes < (release.failed ? 1_440 : 10)
  if (release.complete && !recent) return null

  const percent = Math.round(Math.max(0, Math.min(1, release.progress)) * 100)
  const activeIndex = PHASES.indexOf(release.phase as (typeof PHASES)[number])
  const live = release.complete && !release.failed
  const hint = live
    ? t('release.hint.live')
    : release.failed
      ? release.error || t('release.hint.failed')
      : t(`release.hint.${release.phase}`)

  return (
    <section
      className={`helloada-release ${live ? 'is-live' : ''} ${release.failed ? 'is-failed' : ''}`}
      aria-label={title}
      aria-live="polite"
    >
      <div className="helloada-release-head">
        <span className="helloada-release-mark" aria-hidden="true">
          {live ? <WorkspaceIcon name="check" size={14} /> : <i />}
        </span>
        <div className="helloada-release-copy">
          <strong>{title}</strong>
          <span>{hint}</span>
        </div>
        <div className="helloada-release-meta">
          {live ? (
            <a className="helloada-release-open" href="/" target="_blank" rel="noreferrer">
              {t('release.openLive')}
              <WorkspaceIcon name="external" size={13} />
            </a>
          ) : release.failed ? (
            onAskAda ? <button type="button" onClick={onAskAda}>{t('release.askAda')}</button> : null
          ) : (
            <>
              <em>{percent}%</em>
              <small>{elapsedLabel(release.startedAt, now)}</small>
            </>
          )}
          <button
            className="helloada-release-dismiss"
            type="button"
            onClick={() => setDismissed(`${release.id}:${release.startedAt}`)}
            aria-label={t('release.dismiss')}
            title={t('release.dismiss')}
          >
            <WorkspaceIcon name="close" size={13} />
          </button>
        </div>
      </div>

      {!live && !release.failed ? (
        <div
          className="helloada-release-bar"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          aria-valuetext={`${phaseLabel(release.phase)} ${percent}%`}
        >
          <span style={{ width: `${percent}%` }} />
        </div>
      ) : null}

      <ol className="helloada-release-steps">
        {PHASES.map((phase, index) => {
          const state = live
            ? 'is-done'
            : release.failed
              ? (index <= activeIndex ? 'is-done' : '')
              : index < activeIndex ? 'is-done' : index === activeIndex ? 'is-active' : ''
          return (
            <li key={phase} className={state}>
              <i aria-hidden="true" />
              {phaseLabel(phase)}
            </li>
          )
        })}
      </ol>

      {release.commit ? (
        <p className="helloada-release-commit">
          {t('release.commit')} <code>{release.commit.slice(0, 7)}</code>
          {release.id ? <span> · {release.id}</span> : null}
        </p>
      ) : null}
    </section>
  )
}
