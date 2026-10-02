'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'

import { fetchHelloAda } from '../api/fetchHelloAda'
import { useHelloAdaTranslations } from '../api/useHelloAdaTranslations'
import { useHelloAdaSite } from '../config/provider'

type ConversationHistoryItem = {
  id: number
  title: string
  created_ts?: string | null
  archived_ts?: string | null
}

type DesignHistoryItem = {
  run_id: string
  status: string
  mode: string
  owner_request: string
  conversation_id?: number | null
  created_ts?: string | null
  updated_ts?: string | null
  publishable: boolean
  target?: { mode?: string; scope?: string; path?: string | null } | null
  candidate_sha?: string
  draft_id?: number | null
}

type DraftHistoryItem = {
  id: number
  title: string
  kind: string
  status: string
  created_ts?: string | null
  updated_ts?: string | null
  meta?: { run_id?: string; candidate_sha?: string; target_sha?: string; summary?: string; head_sha?: string; preview?: { requires_build?: boolean } }
}

type PublishHistoryItem = {
  id: number
  ts?: string | null
  summary: string
  path: string
  commit_sha: string
  version_type: string
  reverted_ts?: string | null
}

type WorktreeHistory = {
  available?: boolean
  dirty?: boolean
  branch?: string
  file_count?: number
  files?: Array<{ status?: string; path?: string }>
  error?: string
}

type SourcePreviewHistory = {
  id?: string
  status?: string
  mode?: string
  branch?: string
  commit?: string
  created_at?: string
  updated_at?: string
  preview_url?: string
  runtime_path?: string
  deployment_mode?: string
  error?: string
}

type ContentDraftHistoryItem = {
  id: string
  collection: string
  title: string
  slug?: string
  updatedAt?: string
}

type ContentVersionHistoryItem = {
  id: string
  parent: string
  collection: string
  title: string
  slug?: string
  status: string
  createdAt?: string
  latest?: boolean
}

type HistoryResponse = {
  conversations?: ConversationHistoryItem[]
  design_runs?: DesignHistoryItem[]
  drafts?: DraftHistoryItem[]
  publishes?: PublishHistoryItem[]
  worktree?: WorktreeHistory
  source_preview?: SourcePreviewHistory
  message?: string
}

const dateLabel = (value: string | null | undefined, locale: string, fallback: string) => {
  if (!value) return fallback
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}

const statusLabel = (value: string, translate: (key: string) => string) => {
  const normalized = value.replace(/_/g, ' ')
  const key = `history.status.${value}`
  const translated = translate(key)
  return translated === key ? normalized.replace(/\b\w/g, (letter) => letter.toUpperCase()) : translated
}

export function HelloAdaHistory() {
  const site = useHelloAdaSite()
  const { language, t } = useHelloAdaTranslations()
  const [history, setHistory] = useState<HistoryResponse>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [workingId, setWorkingId] = useState<string>()
  const [contentDrafts, setContentDrafts] = useState<ContentDraftHistoryItem[]>([])
  const [contentVersions, setContentVersions] = useState<ContentVersionHistoryItem[]>([])

  const loadHistory = useCallback(async (signal?: AbortSignal) => {
    const [response, workspaceResponse, contentHistoryResponse] = await Promise.all([
      fetchHelloAda('/api/helloada/history?limit=50', { cache: 'no-store', signal }),
      fetchHelloAda('/api/helloada/workspace', { cache: 'no-store', signal }),
      fetchHelloAda('/api/helloada/content/history', { cache: 'no-store', signal }),
    ])
    const body = (await response.json()) as HistoryResponse
    if (!response.ok) throw new Error(body.message || t('error.historyLoad'))
    setHistory(body)
    if (workspaceResponse.ok) {
      const workspace = (await workspaceResponse.json()) as {
        documents?: Array<Partial<ContentDraftHistoryItem> & { status?: string }>
      }
      setContentDrafts((workspace.documents || [])
        .filter((document) => document.status === 'draft' && document.id && document.collection)
        .map((document) => ({
          id: String(document.id),
          collection: String(document.collection),
          title: String(document.title || document.slug || t('history.untitledContent')),
          ...(document.slug ? { slug: String(document.slug) } : {}),
          ...(document.updatedAt ? { updatedAt: String(document.updatedAt) } : {}),
        })))
    }
    if (contentHistoryResponse.ok) {
      const contentHistory = (await contentHistoryResponse.json()) as { versions?: ContentVersionHistoryItem[] }
      setContentVersions((contentHistory.versions || []).filter((version) => version.id && version.collection && version.parent))
    }
  }, [t])

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      void loadHistory(controller.signal)
        .catch((cause) => {
          if (controller.signal.aborted) return
          setError(cause instanceof Error ? cause.message : t('error.historyLoad'))
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false)
        })
    }, 0)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [loadHistory, t])

  useEffect(() => {
    if (!history?.source_preview?.status || !['queued', 'running'].includes(history.source_preview.status)) return
    const timer = window.setInterval(() => {
      void loadHistory()
    }, 4_000)
    return () => window.clearInterval(timer)
  }, [history?.source_preview?.status, loadHistory])

  const actOnDraft = async (draftId: number, action: 'approve' | 'discard') => {
    const key = `${action}-${draftId}`
    setWorkingId(key)
    setError('')
    setNotice('')
    try {
      const response = await fetchHelloAda(`/api/helloada/drafts/${draftId}/${action}`, { method: 'POST' })
      const body = (await response.json()) as { message?: string; status?: string; deployment?: { status?: string }; published?: { commit_sha?: string } }
      if (!response.ok) throw new Error(body.message || t('error.draftAction'))
      if (action === 'approve') {
        setNotice(body.status === 'publishing' || body.deployment?.status === 'queued'
          ? t('history.publishQueued')
          : t('history.publishedConfirmation'))
      }
      await loadHistory()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('error.draftAction'))
    } finally {
      setWorkingId(undefined)
    }
  }

  const restoreVersion = async (versionId: number) => {
    setWorkingId(`restore-${versionId}`)
    setError('')
    try {
      const response = await fetchHelloAda(`/api/helloada/versions/${versionId}/restore`, { method: 'POST' })
      const body = (await response.json()) as { message?: string }
      if (!response.ok) throw new Error(body.message || t('error.rollback'))
      await loadHistory()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('error.rollback'))
    } finally {
      setWorkingId(undefined)
    }
  }

  const discardWorktree = async () => {
    if (!window.confirm(t('history.discardLocalConfirm'))) return
    setWorkingId('discard-worktree')
    setError('')
    try {
      const response = await fetchHelloAda('/api/helloada/worktree/discard', { method: 'POST' })
      const body = (await response.json()) as { message?: string }
      if (!response.ok) throw new Error(body.message || t('error.worktreeDiscard'))
      await loadHistory()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('error.worktreeDiscard'))
    } finally {
      setWorkingId(undefined)
    }
  }

  const actOnContentDraft = async (draft: ContentDraftHistoryItem, action: 'publish' | 'discard') => {
    const key = `content-${action}-${draft.collection}-${draft.id}`
    setWorkingId(key)
    setError('')
    setNotice('')
    try {
      const endpoint = action === 'publish' ? '/api/helloada/publish' : '/api/helloada/content/discard'
      const body = action === 'publish'
        ? { documents: [{ collection: draft.collection, documentId: draft.id }] }
        : { collection: draft.collection, documentId: draft.id }
      const response = await fetchHelloAda(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const result = (await response.json()) as { message?: string }
      if (!response.ok) throw new Error(result.message || t('error.contentDraftAction'))
      if (action === 'publish') setNotice(t('history.contentPublishedConfirmation'))
      await loadHistory()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('error.contentDraftAction'))
    } finally {
      setWorkingId(undefined)
    }
  }

  const restoreContentVersion = async (version: ContentVersionHistoryItem) => {
    if (!window.confirm(t('history.restoreContentConfirm'))) return
    const key = `content-restore-${version.id}`
    setWorkingId(key)
    setError('')
    setNotice('')
    try {
      const response = await fetchHelloAda('/api/helloada/content/history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ collection: version.collection, versionId: version.id }),
      })
      const result = (await response.json()) as { message?: string }
      if (!response.ok) throw new Error(result.message || t('error.contentVersionRestore'))
      await loadHistory()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('error.contentVersionRestore'))
    } finally {
      setWorkingId(undefined)
    }
  }

  const conversations = history?.conversations || []
  const designRuns = history?.design_runs || []
  const drafts = history?.drafts || []
  const pendingDrafts = drafts.filter((item) => item.status === 'pending')
  const resolvedDrafts = drafts.filter((item) => item.status !== 'pending')
  const publishes = history?.publishes || []
  const worktree = history?.worktree
  const sourcePreview = history?.source_preview

  return (
    <main className="helloada-history">
      <header className="helloada-history-header">
        <div>
          <h2>{t('owner.activity')}</h2>
        </div>
        <Link className="helloada-history-return" href="/admin">
          {t('history.return')} <span aria-hidden="true">↗</span>
        </Link>
      </header>

      {error ? <div className="helloada-alert" role="alert">{error}</div> : null}
      {notice ? <div className="helloada-notice" role="status" aria-live="polite">{notice}</div> : null}
      {loading ? (
        <div className="helloada-history-empty">{t('history.loading')}</div>
      ) : (
        <>
          {worktree?.dirty ? (
            <section className="helloada-history-section helloada-history-wide" aria-labelledby="helloada-local-changes-heading">
              <div className="helloada-history-section-heading">
                <div>
                  <p className="helloada-title-kicker">{t('history.needsAttention')}</p>
                  <h2 id="helloada-local-changes-heading">{t('history.localChanges')}</h2>
                </div>
                <span>{worktree.file_count || worktree.files?.length || 0}</span>
              </div>
              <div className="helloada-history-local-summary">
                <p>{t('history.localChangesIntro')}</p>
                <ul>
                  {(worktree.files || []).slice(0, 8).map((file) => (
                    <li key={`${file.status}-${file.path}`}><code>{file.status}</code> {file.path}</li>
                  ))}
                </ul>
                <button
                  className="helloada-history-action"
                  type="button"
                  disabled={Boolean(workingId)}
                  onClick={() => void discardWorktree()}
                >
                  {workingId === 'discard-worktree' ? t('history.discarding') : t('history.cancelLocalChanges')}
                </button>
              </div>
            </section>
          ) : null}

          {sourcePreview?.status && ['queued', 'running', 'ready', 'failed', 'deployed'].includes(sourcePreview.status) ? (
            <section className="helloada-history-section helloada-history-wide" aria-labelledby="helloada-preview-build-heading">
              <div className="helloada-history-section-heading">
                <div>
                  <p className="helloada-title-kicker">{sourcePreview.mode === 'production' ? t('history.productionRecord') : t('history.previewBuild')}</p>
                  <h2 id="helloada-preview-build-heading">{statusLabel(sourcePreview.status, t)}</h2>
                </div>
                <span aria-label={statusLabel(sourcePreview.status, t)}>•</span>
              </div>
              <p className="helloada-history-preview-note">
                {sourcePreview.status === 'failed'
                  ? sourcePreview.error || t('history.previewFailed')
                  : sourcePreview.status === 'ready'
                    ? t('history.previewReady')
                    : sourcePreview.mode === 'production'
                      ? t('history.productionDeployIntro')
                      : t('history.previewBuildIntro')}
              </p>
              {sourcePreview.status === 'ready' && sourcePreview.mode === 'compiled_preview' ? (
                <Link className="helloada-history-action helloada-history-action-primary" href={site.routes.preview} target="_blank">
                  {t('history.openCompiledPreview')} <span aria-hidden="true">↗</span>
                </Link>
              ) : null}
            </section>
          ) : null}

        <div className="helloada-history-grid">
          <section className="helloada-history-section" aria-labelledby="helloada-conversations-heading">
            <div className="helloada-history-section-heading">
              <div>
                <p className="helloada-title-kicker">{t('history.durableContext')}</p>
                <h2 id="helloada-conversations-heading">{t('history.conversations')}</h2>
              </div>
              <span>{conversations.length}</span>
            </div>
            {conversations.length ? (
              <div className="helloada-history-list">
                {conversations.map((item) => (
                  <Link className="helloada-history-item" href={`/admin?conversation_id=${item.id}`} key={item.id}>
                    <span className="helloada-history-item-mark" aria-hidden="true">◌</span>
                    <span className="helloada-history-item-copy">
                      <strong>{item.title}</strong>
                       <small>{dateLabel(item.created_ts, language, t('history.dateUnavailable'))}{item.archived_ts ? ` · ${t('history.archived')}` : ''}</small>
                    </span>
                    <span className="helloada-history-item-arrow" aria-hidden="true">→</span>
                  </Link>
                ))}
              </div>
            ) : (
              <p className="helloada-history-empty">{t('history.noConversations')}</p>
            )}
          </section>

          <section className="helloada-history-section" aria-labelledby="helloada-design-runs-heading">
            <div className="helloada-history-section-heading">
              <div>
                <p className="helloada-title-kicker">{t('history.reviewableWork')}</p>
                <h2 id="helloada-design-runs-heading">{t('history.designRuns')}</h2>
              </div>
              <span>{designRuns.length}</span>
            </div>
            {designRuns.length ? (
              <div className="helloada-history-list">
                {designRuns.map((item) => (
                  <article className="helloada-history-item is-static" key={item.run_id}>
                    <span className="helloada-history-item-mark" aria-hidden="true">✦</span>
                    <span className="helloada-history-item-copy">
                      <strong>{item.target?.path || item.owner_request || t('history.untitledRun')}</strong>
                      <small>
                         {statusLabel(item.status, t)} · {dateLabel(item.updated_ts || item.created_ts, language, t('history.dateUnavailable'))}
                        {item.publishable ? ` · ${t('history.approvalLane')}` : ` · ${t('history.localReview')}`}
                      </small>
                       {item.target?.scope ? <em>{statusLabel(item.target.scope, t)}</em> : null}
                    </span>
                    <span className="helloada-history-run-id">{item.run_id.slice(0, 8)}</span>
                  </article>
                ))}
              </div>
            ) : (
              <p className="helloada-history-empty">{t('history.noRuns')}</p>
            )}
          </section>

          <section className="helloada-history-section" aria-labelledby="helloada-decisions-heading">
            <div className="helloada-history-section-heading">
              <div>
                <p className="helloada-title-kicker">{t('history.ownerAction')}</p>
                <h2 id="helloada-decisions-heading">{t('history.decisions')}</h2>
              </div>
              <span>{pendingDrafts.length}</span>
            </div>
            {pendingDrafts.length ? (
              <div className="helloada-history-list">
                {pendingDrafts.map((draft) => (
                  <article className="helloada-history-item is-static" key={draft.id}>
                    <span className="helloada-history-item-mark" aria-hidden="true">◈</span>
                    <span className="helloada-history-item-copy">
                      <strong>{draft.title}</strong>
                       <small>{statusLabel(draft.kind, t)} · {dateLabel(draft.updated_ts || draft.created_ts, language, t('history.dateUnavailable'))}</small>
                       {draft.meta?.candidate_sha ? <em>{t('history.candidate')} {draft.meta.candidate_sha.slice(0, 8)}</em> : null}
                    </span>
                    <span className="helloada-history-actions">
                      <button
                        className="helloada-history-action helloada-history-action-primary"
                        type="button"
                        disabled={Boolean(workingId)}
                        onClick={() => void actOnDraft(draft.id, 'approve')}
                      >
                        {workingId === `approve-${draft.id}`
                          ? draft.kind === 'design' ? t('history.approving') : t('history.publishing')
                          : draft.kind === 'design' ? t('history.approve') : t('history.publish')}
                      </button>
                      <button
                        className="helloada-history-action"
                        type="button"
                        disabled={Boolean(workingId)}
                        onClick={() => void actOnDraft(draft.id, 'discard')}
                      >
                        {workingId === `discard-${draft.id}` ? t('history.discarding') : t('history.discard')}
                      </button>
                    </span>
                  </article>
                ))}
              </div>
            ) : (
              <p className="helloada-history-empty">{t('history.noDecisions')}</p>
            )}
          </section>

          <section className="helloada-history-section" aria-labelledby="helloada-content-heading">
            <div className="helloada-history-section-heading">
              <div>
                <p className="helloada-title-kicker">{t('history.contentChangesIntro')}</p>
                <h2 id="helloada-content-heading">{t('history.contentChanges')}</h2>
              </div>
              <span>{contentDrafts.length}</span>
            </div>
            {contentDrafts.length ? (
              <div className="helloada-history-list">
                {contentDrafts.map((draft) => (
                  <article className="helloada-history-item is-static" key={`${draft.collection}-${draft.id}`}>
                    <span className="helloada-history-item-mark" aria-hidden="true">◈</span>
                    <span className="helloada-history-item-copy">
                      <strong>{draft.title}</strong>
                      <small>{draft.collection} · {dateLabel(draft.updatedAt, language, t('history.dateUnavailable'))}</small>
                      {draft.slug ? <em>{draft.slug}</em> : null}
                    </span>
                    <span className="helloada-history-actions">
                      <button
                        className="helloada-history-action helloada-history-action-primary"
                        type="button"
                        disabled={Boolean(workingId)}
                        onClick={() => void actOnContentDraft(draft, 'publish')}
                      >
                        {workingId === `content-publish-${draft.collection}-${draft.id}` ? t('history.publishingContent') : t('history.publishContent')}
                      </button>
                      <button
                        className="helloada-history-action"
                        type="button"
                        disabled={Boolean(workingId)}
                        onClick={() => void actOnContentDraft(draft, 'discard')}
                      >
                        {workingId === `content-discard-${draft.collection}-${draft.id}` ? t('history.discardingContent') : t('history.discardContent')}
                      </button>
                    </span>
                  </article>
                ))}
              </div>
            ) : (
              <p className="helloada-history-empty">{t('history.noContentChanges')}</p>
            )}
          </section>

          {contentVersions.length ? (
            <section className="helloada-history-section" aria-labelledby="helloada-content-versions-heading">
              <div className="helloada-history-section-heading">
                <div>
                  <p className="helloada-title-kicker">{t('history.contentVersionRecord')}</p>
                  <h2 id="helloada-content-versions-heading">{t('history.contentVersions')}</h2>
                </div>
                <span>{contentVersions.length}</span>
              </div>
              <div className="helloada-history-list">
                {contentVersions.slice(0, 16).map((version) => (
                  <article className="helloada-history-item is-static" key={`${version.collection}-${version.id}`}>
                    <span className="helloada-history-item-mark" aria-hidden="true">⌁</span>
                    <span className="helloada-history-item-copy">
                      <strong>{version.title}</strong>
                      <small>{version.collection} · {dateLabel(version.createdAt, language, t('history.dateUnavailable'))}</small>
                      {version.slug ? <em>{version.slug} · {statusLabel(version.status, t)}</em> : null}
                    </span>
                    <button
                      className="helloada-history-action"
                      type="button"
                      disabled={Boolean(workingId)}
                      onClick={() => void restoreContentVersion(version)}
                    >
                      {workingId === `content-restore-${version.id}` ? t('history.preparing') : t('history.prepareContentRollback')}
                    </button>
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          {resolvedDrafts.length ? (
            <section className="helloada-history-section" aria-labelledby="helloada-resolved-heading">
              <div className="helloada-history-section-heading">
                <div>
                  <p className="helloada-title-kicker">{t('history.decisionRecord')}</p>
                  <h2 id="helloada-resolved-heading">{t('history.recentDecisions')}</h2>
                </div>
                <span>{resolvedDrafts.length}</span>
              </div>
              <div className="helloada-history-list">
                {resolvedDrafts.slice(0, 12).map((draft) => (
                  <article className="helloada-history-item is-static" key={`resolved-${draft.id}`}>
                    <span className="helloada-history-item-mark" aria-hidden="true">◌</span>
                    <span className="helloada-history-item-copy">
                      <strong>{draft.title}</strong>
                      <small>{statusLabel(draft.status, t)} · {dateLabel(draft.updated_ts || draft.created_ts, language, t('history.dateUnavailable'))}</small>
                    </span>
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          <section className="helloada-history-section" aria-labelledby="helloada-publishes-heading">
            <div className="helloada-history-section-heading">
              <div>
                <p className="helloada-title-kicker">{t('history.productionRecord')}</p>
                <h2 id="helloada-publishes-heading">{t('history.publishedVersions')}</h2>
              </div>
              <span>{publishes.length}</span>
            </div>
            {publishes.length ? (
              <div className="helloada-history-list">
                {publishes.map((version) => (
                  <article className="helloada-history-item is-static" key={version.id}>
                    <span className="helloada-history-item-mark" aria-hidden="true">⌁</span>
                    <span className="helloada-history-item-copy">
                      <strong>{version.summary || t('history.publishedVersion')}</strong>
                       <small>{statusLabel(version.version_type, t)} · {dateLabel(version.ts, language, t('history.dateUnavailable'))}</small>
                      <em>{version.commit_sha ? version.commit_sha.slice(0, 8) : t('history.commitUnavailable')}</em>
                    </span>
                    <button
                      className="helloada-history-action"
                      type="button"
                      disabled={Boolean(workingId) || Boolean(version.reverted_ts)}
                      onClick={() => void restoreVersion(version.id)}
                    >
                      {workingId === `restore-${version.id}` ? t('history.preparing') : version.reverted_ts ? t('history.superseded') : t('history.prepareRollback')}
                    </button>
                  </article>
                ))}
              </div>
            ) : (
              <p className="helloada-history-empty">{t('history.noPublished')}</p>
            )}
          </section>
        </div>
        </>
      )}
    </main>
  )
}
