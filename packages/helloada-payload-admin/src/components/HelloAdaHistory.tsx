'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'

import { fetchHelloAda } from '../api/fetchHelloAda'
import { useHelloAdaTranslations } from '../api/useHelloAdaTranslations'
import { HelloAdaChatMessage } from './HelloAdaChatMessage'

type DraftItem = {
  id: number
  title: string
  kind: string
  status: string
  created_ts?: string | null
  updated_ts?: string | null
}

type PublishItem = {
  id: number
  ts?: string | null
  summary: string
  commit_sha: string
  version_type: string
  reverted_ts?: string | null
}

type DesignItem = {
  run_id: string
  status: string
  owner_request: string
  created_ts?: string | null
  updated_ts?: string | null
  target?: { path?: string | null } | null
}

type SourcePreview = {
  status?: string
  mode?: string
  created_at?: string
  updated_at?: string
  error?: string
}

type SeoReportItem = {
  id: number
  period: string
  status: string
  summary?: string
  created_ts?: string | null
  completed_ts?: string | null
}

type ExecutionItem = {
  id: string
  kind: 'growth_cycle' | 'seo_report' | 'report' | 'article_research'
  trigger?: string
  period?: string
  status: string
  title?: string
  created_ts?: string | null
  completed_ts?: string | null
  detail_id?: string
  report?: { source: 'draft' | 'seo'; id: number }
}

type ActivityData = {
  drafts?: DraftItem[]
  publishes?: PublishItem[]
  design_runs?: DesignItem[]
  seo_reports?: SeoReportItem[]
  execution_log?: ExecutionItem[]
  source_preview?: SourcePreview
  message?: string
}

type ReportDetail = {
  body?: string
  message?: string
  provenance?: { evidence_hash?: string; site_evidence_included?: boolean; article_research_count?: number }
}
type ExecutionDetail = {
  summary?: string
  summary_key?: string | null
  status?: string
  evidence_sources?: Array<{ id: string; state: string; observed_at?: string | null }>
  decisions?: Array<{ id: number; title: string; state: string }>
  message?: string
}
type TimelineEvent = {
  id: string
  date?: string | null
  title: string
  kind: string
  status?: string
  summary?: string
  report?: { source: 'draft' | 'seo'; id: number }
  executionId?: string
  commit?: string
}

const dateLabel = (value: string | null | undefined, locale: string, fallback: string) => {
  if (!value) return fallback
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}

const labelFor = (value: string, translate: (key: string) => string) => {
  const key = `history.status.${value}`
  const translated = translate(key)
  return translated === key ? value.replace(/_/g, ' ') : translated
}

const isCodeVersion = (value: string) => ['design', 'merge', 'rollback', 'edit'].includes(value)
const isReport = (value: string) => ['report', 'seo_report'].includes(value)
const isTerminal = (value: string) => ['live', 'published', 'approved', 'discarded', 'rejected', 'failed', 'publish_failed', 'cancelled', 'superseded'].includes(value)

export function HelloAdaHistory() {
  const { language, t } = useHelloAdaTranslations()
  const [data, setData] = useState<ActivityData>()
  const [reportBodies, setReportBodies] = useState<Record<string, ReportDetail>>({})
  const [executionDetails, setExecutionDetails] = useState<Record<string, ExecutionDetail>>({})
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<number | string>()
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async (signal?: AbortSignal) => {
    const response = await fetchHelloAda('/api/helloada/history?limit=100', { cache: 'no-store', signal })
    const body = (await response.json()) as ActivityData
    if (!response.ok) throw new Error(body.message || t('error.historyLoad'))
    setData(body)
  }, [t])

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
      .catch((cause) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : t('error.historyLoad'))
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [load, t])

  const versions = useMemo(
    () => (data?.publishes || []).filter((item) => isCodeVersion(item.version_type)),
    [data?.publishes],
  )

  const events = useMemo(() => {
    const rows: TimelineEvent[] = []
    for (const item of data?.publishes || []) {
      if (!isCodeVersion(item.version_type)) continue
      rows.push({ id: `publish:${item.id}`, date: item.ts, title: item.summary || t('history.publishedVersion'),
        kind: item.version_type, status: item.reverted_ts ? 'superseded' : 'published', commit: item.commit_sha })
    }
    for (const item of data?.drafts || []) {
      if (isReport(item.kind)) {
        rows.push({ id: `report:${item.id}`, date: item.updated_ts || item.created_ts, title: item.title,
          kind: 'report', status: item.status, report: { source: 'draft', id: item.id } })
      } else if (isTerminal(item.status) && !['design', 'merge', 'rollback', 'reflection'].includes(item.kind)) {
        rows.push({ id: `decision:${item.id}`, date: item.updated_ts || item.created_ts, title: item.title,
          kind: item.kind, status: item.status })
      }
    }
    for (const item of data?.seo_reports || []) {
      rows.push({ id: `seo-report:${item.id}`, date: item.completed_ts || item.created_ts,
        title: `${t('history.monthlySeoReport')} · ${item.period}`, kind: 'report', status: item.status,
        report: { source: 'seo', id: item.id }, summary: item.summary })
    }
    for (const item of data?.execution_log || []) {
      if (item.kind === 'growth_cycle' && item.detail_id) {
        rows.push({ id: `execution:${item.detail_id}`, date: item.completed_ts || item.created_ts,
          title: t(`history.cycle.${item.trigger || 'scheduled'}`), kind: 'execution', status: item.status,
          executionId: item.detail_id })
      } else if (item.kind === 'article_research' && item.status === 'needs_repair') {
        rows.push({ id: item.id, date: item.completed_ts, title: item.title || t('history.articleResearch'),
          kind: 'execution', status: item.status, summary: t('history.executionIssueNote') })
      }
    }
    for (const item of data?.design_runs || []) {
      if (!isTerminal(item.status)) continue
      rows.push({ id: `design:${item.run_id}`, date: item.updated_ts || item.created_ts,
        title: item.target?.path || item.owner_request || t('history.untitledRun'), kind: 'design', status: item.status })
    }
    const preview = data?.source_preview
    if (preview?.status && isTerminal(preview.status)) {
      rows.push({ id: `preview:${preview.updated_at || preview.created_at || preview.status}`,
        date: preview.updated_at || preview.created_at, title: t('history.previewBuild'), kind: 'execution',
        status: preview.status, summary: preview.error })
    }
    return rows.sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))
  }, [data?.drafts, data?.publishes, data?.design_runs, data?.seo_reports, data?.execution_log, data?.source_preview, t])

  const loadReport = async (report: { source: 'draft' | 'seo'; id: number }) => {
    const key = `${report.source}:${report.id}`
    if (reportBodies[key] !== undefined) return
    setBusyId(key)
    setError('')
    try {
      const endpoint = report.source === 'seo' ? 'seo-reports' : 'drafts'
      const response = await fetchHelloAda(`/api/helloada/history/${endpoint}/${report.id}`, { cache: 'no-store' })
      const body = (await response.json()) as ReportDetail
      if (!response.ok) throw new Error(body.message || t('error.historyLoad'))
      setReportBodies((current) => ({ ...current, [key]: { ...body, body: String(body.body || '') } }))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('error.historyLoad'))
    } finally {
      setBusyId(undefined)
    }
  }

  const loadExecution = async (runId: string) => {
    if (executionDetails[runId] !== undefined) return
    setBusyId(`execution:${runId}`)
    setError('')
    try {
      const response = await fetchHelloAda(`/api/helloada/history/executions/${encodeURIComponent(runId)}`, { cache: 'no-store' })
      const body = (await response.json()) as ExecutionDetail
      if (!response.ok) throw new Error(body.message || t('error.historyLoad'))
      setExecutionDetails((current) => ({ ...current, [runId]: body }))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('error.historyLoad'))
    } finally {
      setBusyId(undefined)
    }
  }

  const reportBody = (report: { source: 'draft' | 'seo'; id: number }) => {
    const key = `${report.source}:${report.id}`
    const detail = reportBodies[key]
    if (!detail) return null
    return <>
      {report.source === 'seo' ? <p className="helloada-history-provenance">
        {t('history.evidenceSources')}: {detail.provenance?.site_evidence_included ? t('history.siteEvidence') : t('history.siteEvidenceMissing')} · {t('history.articleResearch')}: {detail.provenance?.article_research_count ?? 0}
        {detail.provenance?.evidence_hash ? ` · ${t('history.evidenceRef')} ${detail.provenance.evidence_hash.slice(0, 12)}` : ''}
      </p> : null}
      <HelloAdaChatMessage text={detail.body || ''} />
    </>
  }

  const executionBody = (runId: string) => {
    const detail = executionDetails[runId]
    if (!detail) return null
    const summary = detail.summary || (detail.summary_key ? t(`history.executionSummary.${detail.summary_key}`) : '')
    return <div className="helloada-history-execution-detail">
      {summary ? <p>{summary}</p> : null}
      {detail.evidence_sources?.length ? <p className="helloada-history-provenance">
        {t('history.evidenceSources')}: {detail.evidence_sources.map((source) => `${source.id} · ${t(`growth.state_${source.state}`)}`).join(' · ')}
      </p> : null}
      {detail.decisions?.length ? <div><strong>{t('history.relatedDecisions')}</strong><ul>
        {detail.decisions.map((decision) => <li key={decision.id}>{decision.title}</li>)}
      </ul></div> : null}
      {detail.status === 'needs_repair' ? <p className="helloada-history-provenance">{t('history.executionIssueNote')}</p> : null}
    </div>
  }

  const prepareRestore = async (version: PublishItem) => {
    if (busyId || version.reverted_ts) return
    if (!window.confirm(t('history.restoreFrontendConfirm'))) return
    setBusyId(version.id)
    setError('')
    setNotice('')
    try {
      const response = await fetchHelloAda(`/api/helloada/versions/${version.id}/restore`, { method: 'POST' })
      const body = (await response.json()) as { message?: string }
      if (!response.ok) throw new Error(body.message || t('error.rollback'))
      setNotice(t('history.restoreQueued'))
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('error.rollback'))
    } finally {
      setBusyId(undefined)
    }
  }

  return (
    <main className="helloada-history">
      <header className="helloada-history-header">
        <div><p className="helloada-title-kicker">{t('history.record')}</p><h2>{t('owner.activity')}</h2></div>
        <Link className="helloada-history-return" href="/admin">{t('history.return')} <span aria-hidden="true">↗</span></Link>
      </header>
      {error ? <div className="helloada-alert" role="alert">{error}</div> : null}
      {notice ? <div className="helloada-notice" role="status" aria-live="polite">{notice}</div> : null}
      {loading ? <div className="helloada-history-empty">{t('history.loading')}</div> : (
        <div className="helloada-history-grid">
          <section className="helloada-history-section" aria-labelledby="helloada-activity-timeline">
            <div className="helloada-history-section-heading">
              <div><p className="helloada-title-kicker">{t('history.activityRecord')}</p><h2 id="helloada-activity-timeline">{t('history.timeline')}</h2></div>
              <span>{events.length}</span>
            </div>
            {events.length ? <ol className="helloada-history-list helloada-history-timeline">
              {events.map((event) => <li className="helloada-history-item is-static" key={event.id}>
                <span className="helloada-history-item-mark" aria-hidden="true">{event.kind === 'report' ? '≋' : event.kind === 'design' ? '✦' : '⌁'}</span>
                <span className="helloada-history-item-copy">
                  <strong>{event.title}</strong>
                  <small>{labelFor(event.kind, t)} · {dateLabel(event.date, language, t('history.dateUnavailable'))}{event.status ? ` · ${labelFor(event.status, t)}` : ''}</small>
                  {event.commit ? <em>{event.commit.slice(0, 8)}</em> : null}
                  {event.summary ? <p>{event.summary}</p> : null}
                  {event.report ? <details className="helloada-history-report" onToggle={(e) => { if (e.currentTarget.open) void loadReport(event.report!) }}>
                    <summary>{busyId === `${event.report.source}:${event.report.id}` ? t('history.loadingReport') : t('history.openDetails')}</summary>
                    {reportBody(event.report)}
                  </details> : null}
                  {event.executionId ? <details className="helloada-history-report" onToggle={(e) => { if (e.currentTarget.open) void loadExecution(event.executionId!) }}>
                    <summary>{busyId === `execution:${event.executionId}` ? t('history.loadingReport') : t('history.openDetails')}</summary>
                    {executionBody(event.executionId)}
                  </details> : null}
                </span>
              </li>)}</ol> : <p className="helloada-history-empty">{t('history.noActivity')}</p>}
          </section>

          <aside className="helloada-history-section helloada-history-execution" aria-labelledby="helloada-execution-log">
            <div className="helloada-history-section-heading">
              <div><p className="helloada-title-kicker">{t('history.executionRecord')}</p><h2 id="helloada-execution-log">{t('history.latestWork')}</h2></div>
              <span>{data?.execution_log?.length || 0}</span>
            </div>
            {data?.execution_log?.length ? <ol className="helloada-history-list helloada-history-log">
              {data.execution_log.map((item) => {
                const label = item.kind === 'growth_cycle'
                  ? t(`history.cycle.${item.trigger || 'scheduled'}`)
                  : item.kind === 'seo_report'
                  ? `${t('history.monthlySeoReport')} · ${item.period || ''}`
                  : item.title || t('history.monthlySeoReport')
                return <li className="helloada-history-item is-static" key={item.id}>
                  <span className="helloada-history-item-mark" aria-hidden="true">{item.status === 'needs_repair' ? '!' : item.kind.includes('report') || item.kind === 'report' ? '≋' : '✓'}</span>
                  <span className="helloada-history-item-copy">
                    <strong>{label}</strong>
                    <small>{dateLabel(item.completed_ts || item.created_ts, language, t('history.dateUnavailable'))} · {labelFor(item.status, t)}</small>
                    {item.detail_id ? <details className="helloada-history-report" onToggle={(e) => { if (e.currentTarget.open) void loadExecution(item.detail_id!) }}>
                      <summary>{busyId === `execution:${item.detail_id}` ? t('history.loadingReport') : t('history.openDetails')}</summary>
                      {executionBody(item.detail_id)}
                    </details> : item.report ? <details className="helloada-history-report" onToggle={(e) => { if (e.currentTarget.open) void loadReport(item.report!) }}>
                      <summary>{busyId === `${item.report.source}:${item.report.id}` ? t('history.loadingReport') : t('history.openDetails')}</summary>
                      {reportBody(item.report)}
                    </details> : item.status === 'needs_repair' ? <p className="helloada-history-provenance">{t('history.executionIssueNote')}</p> : item.status === 'waiting_for_data' ? <p className="helloada-history-provenance">{t('history.waitingForData')}</p> : null}
                  </span>
                </li>
              })}
            </ol> : <p className="helloada-history-empty">{t('history.noCompletedWork')}</p>}
          </aside>

          <section className="helloada-history-section helloada-history-wide" aria-labelledby="helloada-website-versions">
            <div className="helloada-history-section-heading">
              <div><p className="helloada-title-kicker">{t('history.productionRecord')}</p><h2 id="helloada-website-versions">{t('history.websiteVersions')}</h2></div>
              <span>{versions.length}</span>
            </div>
            <p className="helloada-history-preview-note">{t('history.frontendOnlyNote')}</p>
            {versions.length ? <div className="helloada-history-list">
              {versions.map((version) => <article className="helloada-history-item is-static" key={version.id}>
                <span className="helloada-history-item-mark" aria-hidden="true">⌁</span>
                <span className="helloada-history-item-copy">
                  <strong>{version.summary || t('history.publishedVersion')}</strong>
                  <small>{dateLabel(version.ts, language, t('history.dateUnavailable'))} · {labelFor(version.version_type, t)}</small>
                  <em>{version.commit_sha ? version.commit_sha.slice(0, 8) : t('history.commitUnavailable')}</em>
                </span>
                <button className="helloada-history-action" type="button" disabled={Boolean(busyId) || Boolean(version.reverted_ts)} onClick={() => void prepareRestore(version)}>
                  {busyId === version.id ? t('history.preparing') : version.reverted_ts ? t('history.superseded') : t('history.prepareFrontendRestore')}
                </button>
              </article>)}
            </div> : <p className="helloada-history-empty">{t('history.noPublished')}</p>}
          </section>
        </div>
      )}
    </main>
  )
}
