'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Image from 'next/image'
import { useSearchParams } from 'next/navigation'

import { HelloAdaChatMessage } from './HelloAdaChatMessage'
import { HelloAdaHistory } from './HelloAdaHistory'
import { HelloAdaGrowth } from './HelloAdaGrowth'
import { EditableRichTextEditor } from './EditableRichTextEditor'
import { fetchHelloAda } from '../api/fetchHelloAda'
import { useHelloAdaTranslations } from '../api/useHelloAdaTranslations'
import { mediaReferenceId, mediaUrl as migrationMediaUrl } from '../lib/media'
import { useHelloAdaSite } from '../config/provider'
import { HelloAdaMark } from './HelloAdaLogo'
import { WorkspaceIcon } from './WorkspaceIcon'

type WorkspaceDocument = {
  id: string
  collection: string
  sourceId: string
  slug: string
  title: string
  status: string
}

type WorkspaceRoute = {
  path: string
  kind: string
  collection: string
  sourceId: string
}

type WorkspaceSnapshot = {
  site: { name: string; url: string }
  routes: WorkspaceRoute[]
  documents: WorkspaceDocument[]
  ada: { configured: boolean }
}

type EditablePageEntry = {
  id?: string
  key: string
  label: string
  section?: string | null
  sectionOrder?: number
  type: 'text' | 'richText' | 'image' | 'link'
  editorRole?: 'heading' | 'paragraph' | 'image'
  text?: string | null
  richText?: unknown
  image?: unknown
  sourceType?: 'text' | 'richText' | 'image' | 'link'
  file?: string
  valueStart?: number
  valueEnd?: number
  raw?: string
  value?: string
  sourceHash?: string
  kind?: string
  route?: string
  routes?: string[]
  editable?: boolean
  status?: string
  reason?: string
  contentEdit?: {
    collection: 'pages' | 'products' | 'posts'
    documentId: string
    field: 'editable' | 'gallery' | 'featuredImage' | 'content' | string
    editableId?: string
    index?: number
    contentIndex?: number
    imageIndex?: number
    expectedValue: string
  }
}

type EditablePage = {
  id: string
  title: string
  slug: string
  status: string
  editable: EditablePageEntry[]
}

type ContentField = {
  id?: string
  key?: string
  label?: string
  section?: string
  sectionOrder?: number
  type?: 'text' | 'richText' | 'image' | 'link'
  sourceType?: 'text' | 'richText' | 'image' | 'link'
  editorVisible?: boolean
  editorRole?: 'heading' | 'paragraph' | 'image'
  value?: string
  text?: string
  image?: {
    id?: string
    sourceId?: string
    url?: string
    filename?: string
    alt?: string
  }
  route?: string
  routes?: string[]
  editable?: boolean
  status?: string
  kind?: string
  contentEdit?: {
    collection?: 'pages' | 'products' | 'posts'
    documentId?: string
    field?: 'editable' | 'gallery' | 'featuredImage' | 'content' | string
    editableId?: string
    index?: number
    contentIndex?: number
    imageIndex?: number
    expectedValue?: string
  }
}

type ContentImageResponse = {
  fields?: ContentField[]
  message?: string
}

type EditableMedia = {
  id: string | number
  url?: string | null
  filename?: string | null
  alt?: string | null
  sourceId?: string | null
  sourceUrl?: string | null
  originalUrl?: string | null
  sourcePages?: string[]
  mimeType?: string | null
  portable?: boolean
}

type PreviewEditTarget = {
  key: string
  label: string
  type: EditablePageEntry['type']
  left: number
  top: number
}

type MediaLibraryResponse = {
  media?: EditableMedia[]
  page?: number
  totalDocs?: number
  totalPages?: number
  hasNextPage?: boolean
}

type ChatMessage = {
  role: 'user' | 'assistant' | 'system'
  text: string
  attachments?: ChatAttachment[]
}

type ChatAttachment = {
  type?: string
  asset_id?: number | string
  sourceId?: string | null
  name?: string
  alt_text?: string
  description?: string
  width?: number | null
  height?: number | null
  url?: string | null
  thumbnail_url?: string | null
  preview_url?: string | null
  analysis_status?: string
  analysis_error?: string | null
}

type AdaPhase = 'unknown' | 'intake' | 'incubation' | 'workspace'

type PreviewPlan = {
  mode?: 'overlay' | 'compile'
  status?: 'ready' | 'build_required'
  requires_build?: boolean
  reason?: string
  changed_paths?: string[]
  head_sha?: string
}

type PreviewUiStatus = 'idle' | 'refreshing' | 'ready' | 'build-required' | 'error'
type PreviewViewport = 'desktop' | 'tablet' | 'mobile'

type IntakeResearchStatus = {
  status?: string
  error?: string
  updated_at?: string | null
  themes?: string[]
  audience_needs?: string[]
  trends?: string[]
  latest_learning?: string
  insights?: Array<{
    kind?: string
    summary?: string
    confidence?: number | null
    sources?: Array<{ title?: string; url?: string }>
  }>
  findings?: Array<{
    summary?: string
    source?: { title?: string; url?: string }
  }>
}

type IntakeStatus = {
  session_id?: string
  conversation_id?: number
  status?: string
  revision?: number
  draft_hash?: string
  confirmed?: boolean
  confirmed_revision?: number
  confirmed_revision_id?: number
  readiness?: { state?: string; unresolved_core_paths?: string[] }
  summary?: {
    confirmed?: Record<string, unknown>
    advised?: Record<string, unknown>
    assumed?: unknown[]
    deferred?: unknown[]
    contradictions?: unknown[]
    open_topics?: string[]
  }
  research?: IntakeResearchStatus
}

type PendingAdaJob = {
  jobId: number
  conversationId: number
}

type AdaJobStep = {
  ts?: string
  text?: string
}

type AdaJobResponse = {
  id?: number
  conversation_id?: number
  status?: string
  created_ts?: string
  updated_ts?: string
  steps?: AdaJobStep[]
  result?: { reply?: string; message?: string; preview?: PreviewPlan }
  error?: string
}

const initialMessages: ChatMessage[] = []
const pendingAdaJobStorageKey = 'helloada.pendingAdaJob'

const readPendingAdaJob = (): PendingAdaJob | undefined => {
  if (typeof window === 'undefined') return undefined
  try {
    const value = JSON.parse(window.localStorage.getItem(pendingAdaJobStorageKey) || 'null') as Partial<PendingAdaJob> | null
    if (!value || !Number.isInteger(value.jobId) || !Number.isInteger(value.conversationId)) return undefined
    return { jobId: Number(value.jobId), conversationId: Number(value.conversationId) }
  } catch {
    return undefined
  }
}

const writePendingAdaJob = (job: PendingAdaJob) => {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(pendingAdaJobStorageKey, JSON.stringify(job))
}

const clearPendingAdaJob = (jobId?: number) => {
  if (typeof window === 'undefined') return
  const current = readPendingAdaJob()
  if (!jobId || current?.jobId === jobId) window.localStorage.removeItem(pendingAdaJobStorageKey)
}

const routeLabel = (route: WorkspaceRoute | undefined, homeLabel: string) => {
  if (!route || route.path === '/') return homeLabel
  const value = route.path.replace(/^\//, '').replace(/[-_]+/g, ' ')
  return value.charAt(0).toUpperCase() + value.slice(1)
}

const imageReferenceId = (value: unknown): string => {
  if (typeof value === 'string') return /^https?:\/\//i.test(value) || value.startsWith('/') ? '' : value
  if (typeof value === 'number') return String(value)
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const sourceId = (value as Record<string, unknown>).sourceId
    if (typeof sourceId === 'string' || typeof sourceId === 'number') return String(sourceId)
    const id = (value as Record<string, unknown>).id
    if (typeof id === 'string' || typeof id === 'number') return String(id)
  }
  return ''
}

const publicMediaUrl = (value: unknown, media?: EditableMedia): string => {
  const reference = value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
  const candidate = value || media
  const mapped = candidate && typeof candidate === 'object' && !Array.isArray(candidate)
    ? migrationMediaUrl(candidate as never)
    : typeof candidate === 'string'
      ? migrationMediaUrl(candidate as never)
      : undefined
  if (mapped) return mapped

  const raw = typeof value === 'string'
    ? value.trim()
    : String(reference.url || reference.thumbnailURL || reference.originalUrl || reference.sourceUrl || media?.url || '').trim()
  if (!raw) return ''
  if (/^https?:\/\//i.test(raw) || raw.startsWith('/')) return raw
  return raw
}

const imageReferenceUrl = (value: unknown): string => {
  if (typeof value === 'string') return publicMediaUrl(value)
  if (!value || typeof value !== 'object' || Array.isArray(value)) return ''
  const reference = value as Record<string, unknown>
  return publicMediaUrl(reference)
}

const imageReferenceLabel = (value: unknown): string => {
  if (typeof value === 'string') return value.split('/').pop() || value
  if (!value || typeof value !== 'object' || Array.isArray(value)) return ''
  const reference = value as Record<string, unknown>
  return String(reference.filename || reference.alt || 'Selected image').trim()
}

const imageReferenceValue = (value: unknown): string => {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const reference = value as Record<string, unknown>
    const sourceId = String(reference.sourceId || '').trim()
    if (sourceId) return sourceId
    const resolved = mediaReferenceId(reference.url || reference.originalUrl || reference.sourceUrl)
    if (resolved) return resolved
    return String(reference.url || reference.originalUrl || reference.sourceUrl || '').trim()
  }
  return mediaReferenceId(value) || String(value || '').trim()
}

const previewElementForEntry = (
  document: Document,
  entry: EditablePageEntry,
  _alternate: EditablePageEntry | undefined,
  claimed: Set<Element>,
) => {
  const markedElement = Array.from(document.querySelectorAll('[data-helloada-field]'))
    .find((candidate) => candidate.getAttribute('data-helloada-field') === entry.key)
  if (markedElement && !claimed.has(markedElement)) return markedElement
  const image = entry.image && typeof entry.image === 'object' && !Array.isArray(entry.image)
    ? entry.image as Record<string, unknown>
    : undefined
  const imageUrl = typeof image?.url === 'string' ? image.url : ''
  if (entry.type !== 'image' || !imageUrl) return undefined

  const sourcePath = (value: string) => {
    try {
      const url = new URL(value, document.baseURI)
      return `${url.pathname}${url.search}`
    } catch {
      return value
    }
  }
  const expectedPath = sourcePath(imageUrl)
  return Array.from(document.querySelectorAll('img')).find((candidate) => {
    if (claimed.has(candidate)) return false
    const source = candidate.currentSrc || candidate.getAttribute('src') || ''
    return source && sourcePath(source) === expectedPath
  })
}

const previewElementFromPointer = (
  document: Document,
  target: Element,
) => {
  let element: Element | null = target
  while (element && element !== document.body) {
    if (element.hasAttribute('data-helloada-field')) return element
    element = element.parentElement
  }
  return undefined
}

const previewImageFromPointer = (
  document: Document,
  target: Element,
  entries: EditablePageEntry[],
) => {
  const sourcePath = (value: string) => {
    try {
      const url = new URL(value, document.baseURI)
      return `${url.pathname}${url.search}`
    } catch {
      return value
    }
  }
  let element: Element | null = target
  while (element && element !== document.body) {
    if (element.tagName.toLowerCase() === 'img') {
      const source = element as HTMLImageElement
      const sourcePathname = sourcePath(source.currentSrc || source.getAttribute('src') || '')
      const entry = entries.find((candidate) => (
        candidate.type === 'image'
        && candidate.image && typeof candidate.image === 'object' && !Array.isArray(candidate.image)
        && typeof (candidate.image as Record<string, unknown>).url === 'string'
        && sourcePath((candidate.image as Record<string, unknown>).url as string) === sourcePathname
      ))
      if (entry) return { element, entry }
    }
    element = element.parentElement
  }
  return undefined
}

function AdminMediaThumbnail({
  src,
  alt,
  width,
  height,
  className,
  unavailableLabel = 'Image unavailable',
}: {
  src: string
  alt: string
  width: number
  height: number
  className?: string
  unavailableLabel?: string
}) {
  const [failed, setFailed] = useState(false)
  if (!src || failed) return <span className={`${className || ''} helloada-media-thumbnail-fallback`.trim()} aria-label={unavailableLabel}>{unavailableLabel}</span>
  return <Image src={src} alt={alt} width={width} height={height} unoptimized className={className} onError={() => setFailed(true)} />
}

const lexicalDocumentFromText = (value: string) => ({
  root: {
    type: 'root',
    children: value.split(/\r?\n/).map((text) => ({
      type: 'paragraph',
      children: text ? [{ detail: 0, format: 0, mode: 'normal', style: '', text, type: 'text', version: 1 }] : [],
      direction: null,
      format: '',
      indent: 0,
      version: 1,
    })),
    direction: null,
    format: '',
    indent: 0,
    version: 1,
  },
})

const textFromLexicalNode = (value: unknown): string => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return ''
  const node = value as Record<string, unknown>
  if (typeof node.text === 'string') return node.text
  if (!Array.isArray(node.children)) return ''
  return node.children.map(textFromLexicalNode).join('')
}

const sourceTextForRichText = (value: unknown): string => {
  if (typeof value === 'string') return value
  if (!value || typeof value !== 'object' || Array.isArray(value)) return ''
  const root = (value as Record<string, unknown>).root
  if (!root || typeof root !== 'object' || Array.isArray(root)) return ''
  const children = (root as Record<string, unknown>).children
  if (!Array.isArray(children)) return ''
  return children.map(textFromLexicalNode).filter(Boolean).join('\n')
}

const editorEntryFromContent = (field: ContentField): EditablePageEntry | undefined => {
  const contentEdit = field.contentEdit
  if (
    !field.id
    || field.editorVisible !== true
    || field.editable === false
    || field.status !== 'editable'
    || !contentEdit?.collection
    || !contentEdit.documentId
    || !contentEdit.field
    || contentEdit.expectedValue === undefined
  ) return undefined

  const value = field.value || contentEdit.expectedValue || ''
  const type = field.type || (field.image ? 'image' : 'text')
  const image = field.image || {}
  return {
    id: field.id,
    key: field.key || field.id,
    label: field.label || (type === 'image' ? 'Image' : 'Page content'),
    section: field.section || (type === 'image' ? 'Images' : 'Page content'),
    sectionOrder: field.sectionOrder,
    type,
    sourceType: field.sourceType || type,
    editorRole: field.editorRole || (type === 'image' ? 'image' : 'paragraph'),
    ...(type === 'image'
      ? {
          image: {
            ...(image.id ? { id: image.id } : {}),
            ...(image.sourceId || value ? { sourceId: image.sourceId || value } : {}),
            url: image.url || '',
            filename: image.filename || field.label || 'Image',
            alt: image.alt || field.label || 'Image',
          },
        }
      : {
          text: field.text || value,
          ...(type === 'richText' ? { richText: lexicalDocumentFromText(field.text || value) } : {}),
        }),
    value,
    route: field.route,
    routes: field.routes,
    editable: true,
    status: 'editable',
    kind: 'content',
    contentEdit: {
      collection: contentEdit.collection,
      documentId: contentEdit.documentId,
      field: contentEdit.field,
      ...(contentEdit.editableId ? { editableId: contentEdit.editableId } : {}),
      ...(contentEdit.index !== undefined ? { index: contentEdit.index } : {}),
      ...(contentEdit.contentIndex !== undefined ? { contentIndex: contentEdit.contentIndex } : {}),
      ...(contentEdit.imageIndex !== undefined ? { imageIndex: contentEdit.imageIndex } : {}),
      expectedValue: contentEdit.expectedValue,
    },
  }
}

const mergeEditorEntries = (...groups: EditablePageEntry[][]) => {
  const seen = new Set<string>()
  return groups.flat().filter((entry) => {
    if (seen.has(entry.key)) return false
    seen.add(entry.key)
    return true
  })
}

const editorEntryValue = (entry: EditablePageEntry) => {
  if (entry.type === 'image') return imageReferenceValue(entry.image)
  if (entry.type === 'richText') return entry.text ?? sourceTextForRichText(entry.richText)
  return entry.text || ''
}

const editorRoleLabel = (entry: EditablePageEntry) => {
  if (entry.editorRole === 'heading') return 'Heading'
  if (entry.editorRole === 'image') return 'Image'
  return 'Paragraph'
}

const displayEditorLabel = (entry: EditablePageEntry, entries: EditablePageEntry[], index: number) => {
  const matching = entries.filter((candidate) => candidate.label === entry.label)
  if (matching.length < 2) return entry.label
  const occurrence = entries.slice(0, index + 1).filter((candidate) => candidate.label === entry.label).length
  return `${entry.label} ${occurrence}`
}

type BriefEntry = {
  path: string
  value: unknown
  note?: string
}

const briefEntriesFrom = (value: unknown): BriefEntry[] => {
  if (Array.isArray(value)) {
    return value.map((item, index) => {
      if (item && typeof item === 'object') {
        const row = item as Record<string, unknown>
        return {
          path: String(row.path || `item-${index + 1}`),
          value: row.value,
          note: row.note ? String(row.note) : undefined,
        }
      }
      return { path: `item-${index + 1}`, value: item }
    })
  }
  if (!value || typeof value !== 'object') return []
  return Object.entries(value as Record<string, unknown>).map(([path, item]) => ({ path, value: item }))
}

const briefPathLabel = (path: string) => {
  const value = path.split('.').pop() || path
  return value
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[-_]+/g, ' ')
    .replace(/^./, (character) => character.toUpperCase())
}

const briefValueLabel = (value: unknown): string => {
  if (value === undefined || value === null || value === '') return '—'
  if (Array.isArray(value)) return value.map((item) => briefValueLabel(item)).join(', ')
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return '—'
    }
  }
  return String(value)
}

const researchEntriesFrom = (research: IntakeResearchStatus | undefined): BriefEntry[] => {
  if (!research) return []
  const entries: BriefEntry[] = []
  if (research.status && research.status !== 'not_started') {
    entries.push({ path: 'research.status', value: research.status, note: research.error || undefined })
  }
  for (const [index, value] of (research.audience_needs || []).entries()) {
    entries.push({ path: `audience_needs.${index + 1}`, value })
  }
  for (const [index, value] of (research.trends || []).entries()) {
    entries.push({ path: `trends.${index + 1}`, value })
  }
  for (const [index, insight] of (research.insights || []).entries()) {
    const sources = (insight.sources || [])
      .map((source) => source.title || source.url)
      .filter(Boolean)
      .join(', ')
    entries.push({
      path: `research.${insight.kind || `signal-${index + 1}`}`,
      value: insight.summary || '—',
      note: sources ? `Evidence: ${sources}` : 'Evidence-linked inference',
    })
  }
  if (!entries.length) {
    for (const [index, finding] of (research.findings || []).slice(0, 4).entries()) {
      const source = finding.source?.title || finding.source?.url
      entries.push({
        path: `research.finding-${index + 1}`,
        value: finding.summary || '—',
        note: source ? `Source: ${source}` : undefined,
      })
    }
  }
  if (!entries.length && research.latest_learning) {
    entries.push({ path: 'research.latest_learning', value: research.latest_learning })
  }
  return entries
}

export function WebsiteWorkspace() {
  const searchParams = useSearchParams()
  if (searchParams.get('view') === 'history') return <HelloAdaHistory />
  if (searchParams.get('view') === 'growth') return <HelloAdaGrowth />
  return <ReviewWorkspace />
}

function ReviewWorkspace() {
  const searchParams = useSearchParams()
  const { language, t } = useHelloAdaTranslations()
  const site = useHelloAdaSite()
  const [workspace, setWorkspace] = useState<WorkspaceSnapshot>()
  const [websitePresent, setWebsitePresent] = useState(true)
  const [selectedRoute, setSelectedRoute] = useState('/')
  const [previewViewport, setPreviewViewport] = useState<PreviewViewport>('desktop')
  const [mobilePane, setMobilePane] = useState<'ada' | 'website'>('ada')
  const [manualEditing, setManualEditing] = useState(false)
  const [adaUnavailable, setAdaUnavailable] = useState(false)
  const [previewStatus, setPreviewStatus] = useState<PreviewUiStatus>('idle')
  const [previewPlan, setPreviewPlan] = useState<PreviewPlan>()
  const [message, setMessage] = useState('')
  const preparedAsk = searchParams.get('ask')
  useEffect(() => {
    if (!preparedAsk) return
    setMessage(preparedAsk.slice(0, 8000))
    setMobilePane('ada')
  }, [preparedAsk])
  const [conversationId, setConversationId] = useState<number>()
  const [pendingAdaJob, setPendingAdaJob] = useState<PendingAdaJob>()
  const [adaSteps, setAdaSteps] = useState<AdaJobStep[]>([])
  const [adaPhase, setAdaPhase] = useState<AdaPhase>('unknown')
  const [intakeStatus, setIntakeStatus] = useState<IntakeStatus>()
  const [messages, setMessages] = useState(initialMessages)
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [accepting, setAccepting] = useState(false)
  const [error, setError] = useState('')
  const [previewRevision, setPreviewRevision] = useState(0)
  const [pendingAttachments, setPendingAttachments] = useState<ChatAttachment[]>([])
  const [uploadingMedia, setUploadingMedia] = useState(false)
  const [briefOpen, setBriefOpen] = useState(false)
  const [briefCorrection, setBriefCorrection] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)
  const [editorLoading, setEditorLoading] = useState(false)
  const [editorSaving, setEditorSaving] = useState(false)
  const [editorPage, setEditorPage] = useState<EditablePage>()
  const [editorEntries, setEditorEntries] = useState<EditablePageEntry[]>([])
  const [reviewFields, setReviewFields] = useState<EditablePageEntry[]>([])
  const [, setReviewFieldsLoading] = useState(false)
  const [editorMedia, setEditorMedia] = useState<EditableMedia[]>([])
  const [editorMediaLoading, setEditorMediaLoading] = useState(false)
  const [editorMediaHasNext, setEditorMediaHasNext] = useState(false)
  const [editorMediaSearch, setEditorMediaSearch] = useState('')
  const [imagePickerKey, setImagePickerKey] = useState<string>()
  const [editorError, setEditorError] = useState('')
  const [editorNotice, setEditorNotice] = useState('')
  const [publishNotice, setPublishNotice] = useState('')
  const [previewEditTargets, setPreviewEditTargets] = useState<PreviewEditTarget[]>([])
  const [activePreviewEditKey, setActivePreviewEditKey] = useState<string>()
  const [pendingChanges, setPendingChanges] = useState<Record<string, EditablePageEntry>>({})
  const [pendingSaving, setPendingSaving] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [draftUpdatedKey, setDraftUpdatedKey] = useState<string>()
  const [fieldEditorKey, setFieldEditorKey] = useState<string>()
  const [fieldEditorEntry, setFieldEditorEntry] = useState<EditablePageEntry>()
  const [fieldEditorError, setFieldEditorError] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const editorImageInputRef = useRef<HTMLInputElement>(null)
  const fieldImageInputRef = useRef<HTMLInputElement>(null)
  const previewFrameRef = useRef<HTMLIFrameElement>(null)
  const publishDialogRef = useRef<HTMLDialogElement>(null)
  const editorImageTargetRef = useRef<string | undefined>(undefined)
  const messageInputRef = useRef<HTMLTextAreaElement>(null)
  const chatLogRef = useRef<HTMLDivElement>(null)
  const pendingChangesRef = useRef<Record<string, EditablePageEntry>>({})
  const activePreviewEditKeyRef = useRef<string | undefined>(undefined)
  const activePreviewElementRef = useRef<Element | undefined>(undefined)
  const selectedRouteRef = useRef(selectedRoute)
  const userNearBottomRef = useRef(true)
  const lastMessageCountRef = useRef(0)
  const previousSendingRef = useRef(false)
  const activeAdaPollRef = useRef<number | undefined>(undefined)
  const chatWorking = sending || Boolean(pendingAdaJob)

  const scrollChatToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    const element = chatLogRef.current
    if (!element) return
    const scroll = () => element.scrollTo({ top: element.scrollHeight, behavior })
    if (typeof window !== 'undefined') window.requestAnimationFrame(scroll)
    else scroll()
  }, [])

  useEffect(() => {
    pendingChangesRef.current = pendingChanges
    activePreviewEditKeyRef.current = activePreviewEditKey
    selectedRouteRef.current = selectedRoute
  }, [activePreviewEditKey, pendingChanges, selectedRoute])

  const selectedRouteData = useMemo(
    () => workspace?.routes.find((route) => route.path === selectedRoute),
    [selectedRoute, workspace],
  )

  const selectedDocument = useMemo(
    () => workspace?.documents.find((document) => document.sourceId && document.sourceId === selectedRouteData?.sourceId),
    [selectedRouteData, workspace],
  )

  const canEditPage = Boolean(
    websitePresent
      && adaPhase === 'workspace'
      && workspace,
  )

  const previewUrl = useMemo(() => {
    if (typeof window === 'undefined') return selectedRoute
    const path = selectedRoute === '/' ? '' : selectedRoute.replace(/^\//, '')
    const baseUrl = `${window.location.origin}${site.routes.preview}/${path}`
    if (!previewRevision) return baseUrl
    return `${baseUrl}${baseUrl.includes('?') ? '&' : '?'}helloada_revision=${previewRevision}`
  }, [previewRevision, selectedRoute, site.routes.preview])

  const handlePreviewLoad = useCallback(() => {
    if (previewPlan?.requires_build) {
      setPreviewStatus('build-required')
      return
    }
    setPreviewStatus('ready')
  }, [previewPlan])

  const previewStatusMessage = previewStatus === 'refreshing'
    ? t('workspace.previewRefreshing')
    : previewStatus === 'build-required'
      ? t('workspace.previewBuildRequired')
      : previewStatus === 'error'
        ? t('workspace.previewError')
        : ''

  const selectedTarget = useMemo(() => {
    if (!websitePresent || adaPhase === 'unknown' || adaPhase === 'intake') return undefined
    const targetMode = adaPhase === 'workspace' ? 'workspace' : 'incubation'
    return {
      mode: targetMode,
      scope: targetMode === 'workspace' ? 'selected_page' : 'selected_page_reference',
      site: {
        name: workspace?.site.name || site.siteName,
        url: workspace?.site.url || '',
        routes: (workspace?.routes || []).slice(0, 40).map((route) => ({
          path: route.path,
          kind: route.kind,
          collection: route.collection,
          sourceId: route.sourceId,
        })),
      },
      route: {
        path: selectedRoute,
        kind: selectedRouteData?.kind || '',
        sourceId: selectedRouteData?.sourceId || '',
      },
      preview: {
        state: 'draft',
        url: previewUrl,
        revision: previewRevision,
      },
      surface: 'The Ada conversation and the website preview share this workspace. The selected page is visible in the website window.',
      payload: selectedDocument
        ? {
            collection: selectedDocument.collection,
            id: selectedDocument.id,
            sourceId: selectedDocument.sourceId,
            slug: selectedDocument.slug,
            status: selectedDocument.status,
          }
        : null,
    }
  }, [adaPhase, previewRevision, previewUrl, selectedDocument, selectedRoute, selectedRouteData, site.siteName, websitePresent, workspace])

  const loadEditorMedia = useCallback(async (page: number, append: boolean, search: string) => {
    setEditorMediaLoading(true)
    try {
      const params = new URLSearchParams({ limit: '72', page: String(page) })
      if (search.trim()) params.set('search', search.trim())
      const response = await fetchHelloAda(`/api/helloada/media-library?${params.toString()}`, { cache: 'no-store' })
      const body = (await response.json()) as MediaLibraryResponse & { message?: string }
      if (!response.ok) throw new Error(body.message || t('error.pageLoad'))
      const nextMedia = (body.media || []).map((media) => ({
        ...media,
        url: publicMediaUrl(media),
      }))
      setEditorMedia((current) => {
        if (!append) return nextMedia
        const known = new Set(current.map((media) => String(media.id)))
        return [...current, ...nextMedia.filter((media) => !known.has(String(media.id)))]
      })
      setEditorMediaHasNext(body.hasNextPage === true)
    } catch (cause) {
      if (!append) setEditorMedia([])
      setEditorMediaHasNext(false)
      setEditorError(cause instanceof Error ? cause.message : t('error.pageLoad'))
    } finally {
      setEditorMediaLoading(false)
    }
  }, [t])

  const loadContentFields = useCallback(async (route = selectedRoute) => {
    const [fieldsResponse, imagesResponse] = await Promise.all([
      fetchHelloAda(`/api/helloada/page-fields?route=${encodeURIComponent(route)}`, { cache: 'no-store' }),
      fetchHelloAda(`/api/helloada/page-images?route=${encodeURIComponent(route)}`, { cache: 'no-store' }),
    ])
    const fieldsBody = (await fieldsResponse.json()) as ContentImageResponse
    const imagesBody = (await imagesResponse.json()) as ContentImageResponse
    if (!fieldsResponse.ok && !imagesResponse.ok) {
      throw new Error(fieldsBody.message || imagesBody.message || t('error.pageLoad'))
    }
    const fields = [
      ...(fieldsResponse.ok ? fieldsBody.fields || [] : []),
      ...(imagesResponse.ok ? imagesBody.fields || [] : []),
    ]
      .map(editorEntryFromContent)
      .filter((entry): entry is EditablePageEntry => Boolean(entry))
    return { fields: mergeEditorEntries(fields) }
  }, [selectedRoute, t])

  const loadEditorFields = useCallback(async (route = selectedRoute) => {
    const { fields: contentFields } = await loadContentFields(route)
    return { fields: contentFields }
  }, [loadContentFields, selectedRoute])

  const refreshReviewFields = useCallback(async () => {
    if (!canEditPage) {
      setReviewFields([])
      setReviewFieldsLoading(false)
      return
    }
    const route = selectedRoute
    setReviewFieldsLoading(true)
    try {
      const { fields } = await loadContentFields(route)
      if (selectedRouteRef.current === route) setReviewFields(fields)
    } catch {
      // The preview remains useful if the optional quick-edit index is briefly
      // unavailable. The full editor will show the actionable error later.
      if (selectedRouteRef.current === route) setReviewFields([])
    } finally {
      setReviewFieldsLoading(false)
    }
  }, [canEditPage, loadContentFields, selectedRoute])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshReviewFields()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [refreshReviewFields])

  const loadWorkspace = useCallback((background = false) => {
    if (!background) setLoading(true)
    setError('')
    void fetchHelloAda('/api/helloada/workspace', { cache: 'no-store' })
      .then(async (response) => {
        const body = (await response.json()) as WorkspaceSnapshot & { message?: string }
        if (!response.ok) throw new Error(body.message || t('error.workspaceLoad'))
        setWorkspace(body)
      })
      .catch((cause) => {
        setError(cause instanceof Error ? cause.message : t('error.workspaceLoad'))
      })
      .finally(() => setLoading(false))
  }, [t])

  const loadPreviewPlan = useCallback(async () => {
    try {
      const response = await fetchHelloAda('/api/helloada/drafts?status=pending', { cache: 'no-store' })
      const body = (await response.json()) as {
        drafts?: Array<{ kind?: string; meta?: { preview?: PreviewPlan; head_sha?: string } }>
      }
      if (!response.ok) return
      const draft = (body.drafts || []).find((item) => item.kind === 'merge')
      const plan = draft?.meta?.preview
      if (!plan) {
        setPreviewPlan(undefined)
        return
      }
      const headSha = draft?.meta?.head_sha || plan.head_sha || ''
      setPreviewPlan({ ...plan, head_sha: headSha })
      if (!plan.requires_build) return

      const latestResponse = await fetchHelloAda('/api/helloada/source/preview?branch=preview', { cache: 'no-store' })
      const latest = (await latestResponse.json()) as {
        id?: string
        status?: string
        commit?: string
        error?: string
      }
      const sameRevision = !headSha || !latest.commit || latest.commit === headSha
      if (latestResponse.ok && sameRevision && latest.status === 'ready' && latest.id) {
        setPreviewPlan({ ...plan, head_sha: headSha, status: 'ready', requires_build: false })
        setPreviewStatus('refreshing')
        setPreviewRevision((current) => current + 1)
        return
      }
      if (latestResponse.ok && sameRevision && latest.status === 'failed') {
        setPreviewStatus('error')
        setError(latest.error || t('workspace.previewError'))
        return
      }

      // The backend deduplicates the exact branch/commit, so this is safe to
      // repeat while the build is queued or running and also repairs a stale
      // status left by a process restart.
      if (!latestResponse.ok || !sameRevision || !['queued', 'running'].includes(latest.status || '')) {
        const startResponse = await fetchHelloAda('/api/helloada/source/preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ branch: 'preview', ...(headSha ? { commit: headSha } : {}), mode: 'compiled_preview' }),
        })
        if (!startResponse.ok) {
          const startBody = (await startResponse.json()) as { message?: string }
          throw new Error(startBody.message || t('workspace.previewError'))
        }
      }
      setPreviewStatus('refreshing')
    } catch (cause) {
      setPreviewStatus('error')
      setError(cause instanceof Error ? cause.message : t('workspace.previewError'))
    }
  }, [t])

  const openEditor = useCallback((focusKey?: string) => {
    if (!canEditPage) return
    const knownFields = reviewFields.map((entry) => pendingChangesRef.current[entry.key] || entry)
    const title = routeLabel(selectedRouteData, selectedRoute === '/' ? t('workspace.home') : selectedRoute)
    setEditorOpen(true)
    // Open immediately with the fields already declared for this route.
    // The authenticated Payload route refreshes the same registry below.
    setEditorLoading(false)
    setEditorPage({
      id: `source:${selectedRoute}`,
      title,
      slug: selectedRoute,
      status: 'draft',
      editable: knownFields,
    })
    setEditorEntries(knownFields)
    setEditorMedia([])
    setEditorMediaHasNext(false)
    setEditorMediaSearch('')
    const focusedKnownEntry = focusKey ? knownFields.find((entry) => entry.key === focusKey) : undefined
    setImagePickerKey(focusedKnownEntry?.type === 'image' ? focusKey : undefined)
    setEditorError('')
    setEditorNotice('')

    void loadEditorFields()
       .then(({ fields }) => {
        if (selectedRouteRef.current !== selectedRoute) return
        setReviewFields(fields)
        const visibleFields = fields.map((entry) => pendingChangesRef.current[entry.key] || entry)
        setEditorEntries((current) => mergeEditorEntries(visibleFields, current))
        setEditorPage((current) => current
          ? { ...current, editable: mergeEditorEntries(visibleFields, current.editable) }
          : current)
        const focusedEntry = focusKey ? fields.find((entry) => entry.key === focusKey) : undefined
        if (focusedEntry?.type === 'image') setImagePickerKey(focusKey)
      })
      .catch((cause) => {
        if (!knownFields.length) setEditorError(cause instanceof Error ? cause.message : t('error.pageLoad'))
      })
  }, [canEditPage, loadEditorFields, reviewFields, selectedRoute, selectedRouteData, t])

  const closeEditor = useCallback(() => {
    if (editorSaving) return
    setEditorOpen(false)
    editorImageTargetRef.current = undefined
    setEditorError('')
    setEditorNotice('')
  }, [editorSaving])

  const updateEditorEntry = useCallback((key: string, value: Partial<EditablePageEntry>) => {
    setEditorEntries((current) => current.map((entry) => entry.key === key ? { ...entry, ...value } : entry))
  }, [])

  const chooseEditorMedia = useCallback((key: string, value: string) => {
    const selected = editorMedia.find((media) => String(media.id) === value)
    updateEditorEntry(key, {
      image: selected
        ? { id: selected.id, sourceId: selected.sourceId || undefined, url: publicMediaUrl(selected), filename: selected.filename || undefined, alt: selected.alt || undefined }
        : value
          ? { url: value, filename: value.split('/').pop() || 'Selected image' }
          : null,
    })
    setImagePickerKey(undefined)
  }, [editorMedia, updateEditorEntry])

  const uploadEditorImage = useCallback(async (file: File, key: string) => {
    setEditorError('')
    const form = new FormData()
    form.append('file', file)
    try {
      const response = await fetchHelloAda('/api/helloada/media/upload', { method: 'POST', body: form })
      const body = (await response.json()) as { attachment?: ChatAttachment; message?: string }
      const uploadedUrl = publicMediaUrl(body.attachment?.url || body.attachment?.preview_url || '', {
        id: body.attachment?.asset_id || '',
        filename: body.attachment?.name || 'image',
      })
      if (!response.ok || !body.attachment?.asset_id || !uploadedUrl) throw new Error(body.message || t('error.pageImageUpload'))
      updateEditorEntry(key, {
        image: {
          id: body.attachment.asset_id,
          sourceId: body.attachment.sourceId || undefined,
          url: uploadedUrl,
          filename: body.attachment.name || undefined,
          alt: body.attachment.alt_text || undefined,
        },
      })
      setEditorMedia((current) => [
        {
          id: body.attachment?.asset_id as string | number,
          sourceId: body.attachment?.sourceId || null,
          url: uploadedUrl || null,
          filename: body.attachment?.name || 'image',
          alt: body.attachment?.alt_text || 'HelloAda image',
        },
        ...current.filter((media) => String(media.id) !== String(body.attachment?.asset_id)),
      ])
      setEditorNotice(t('workspace.pageImageUploaded'))
    } catch (cause) {
      setEditorError(cause instanceof Error ? cause.message : t('error.pageImageUpload'))
    }
  }, [t, updateEditorEntry])

  const saveEditor = useCallback(() => {
    if (!editorPage || editorSaving) return
    setEditorSaving(true)
    setEditorError('')
    setEditorNotice('')
    const changedEntries = editorEntries.filter((entry) => {
      if (entry.editable === false) return false
      const baseline = reviewFields.find((candidate) => candidate.key === entry.key)
      return editorEntryValue(entry) !== (baseline ? editorEntryValue(baseline) : entry.value || '')
    })
    setPendingChanges((current) => {
      const next = { ...current }
      for (const entry of editorEntries) {
        if (entry.editable === false) continue
        const baseline = reviewFields.find((candidate) => candidate.key === entry.key)
        const baselineValue = baseline ? editorEntryValue(baseline) : entry.value || ''
        if (editorEntryValue(entry) === baselineValue) delete next[entry.key]
        else next[entry.key] = entry
      }
      return next
    })
    setEditorNotice(changedEntries.length ? t('workspace.pageChangesStaged') : t('workspace.pageNoChanges'))
    setEditorOpen(false)
    setEditorSaving(false)
  }, [editorEntries, editorPage, editorSaving, reviewFields, t])

  const rememberPendingAdaJob = useCallback((job: PendingAdaJob) => {
    setPendingAdaJob((current) => (
      current?.jobId === job.jobId && current.conversationId === job.conversationId
        ? current
        : job
    ))
    writePendingAdaJob(job)
  }, [])

  const forgetPendingAdaJob = useCallback((jobId?: number) => {
    setPendingAdaJob((current) => (!jobId || current?.jobId === jobId ? undefined : current))
    clearPendingAdaJob(jobId)
  }, [])

  const startNewChat = useCallback(() => {
    if (chatWorking || adaPhase !== 'workspace') return
    setConversationId(undefined)
    setMessages([])
    setMessage('')
    setPendingAttachments([])
    setAdaSteps([])
    setError('')
    userNearBottomRef.current = true
    lastMessageCountRef.current = 0
    previousSendingRef.current = false
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem('helloada.activeConversationId')
      window.setTimeout(() => messageInputRef.current?.focus(), 0)
    }
  }, [adaPhase, chatWorking])

  const loadAdaStatus = useCallback((activeConversationId?: number, background = false, refreshWorkspace = true) => {
    const query = new URLSearchParams({ status: '1' })
    if (activeConversationId) query.set('conversation_id', String(activeConversationId))
    void fetchHelloAda(`/api/helloada/ada?${query.toString()}`, { cache: 'no-store' })
      .then(async (response) => {
        const body = (await response.json()) as {
          mode?: AdaPhase
          phase?: AdaPhase
          conversation_id?: number
          website_present?: boolean
          intake?: IntakeStatus
          active_job?: {
            id?: number
            conversation_id?: number
            status?: string
          } | null
        }
        if (!response.ok) throw new Error(t('error.adaPhase'))
        setAdaUnavailable(false)
        const phase = body.phase || body.mode
        setAdaPhase(phase === 'intake' || phase === 'incubation' || phase === 'workspace' ? phase : 'workspace')
        if (typeof body.website_present === 'boolean') {
          setWebsitePresent(body.website_present)
          if (!body.website_present) {
            setWorkspace(undefined)
            setError('')
            setLoading(false)
          } else if (refreshWorkspace) {
            loadWorkspace(background)
          }
        } else if (refreshWorkspace) {
          loadWorkspace(background)
        }
        setIntakeStatus(body.intake)
        if (body.conversation_id) setConversationId(body.conversation_id)
        if (body.active_job?.id && body.active_job.conversation_id) {
          const pendingJob: PendingAdaJob = {
            jobId: body.active_job.id,
            conversationId: body.active_job.conversation_id,
          }
          rememberPendingAdaJob(pendingJob)
        }
      })
      .catch(() => {
        // Do not guess that intake is complete. Website context stays dormant
        // until the server proves the explicit acceptance transition.
        setAdaPhase('unknown')
        setAdaUnavailable(true)
        loadWorkspace(background)
      })
  }, [loadWorkspace, rememberPendingAdaJob, t])

  const completeAdaJob = useCallback((jobId: number, job: AdaJobResponse) => {
    const reply = job.result?.reply || job.result?.message
    if (!reply) {
      setError(t('error.adaComplete'))
      forgetPendingAdaJob(jobId)
      setSending(false)
      return
    }
    setMessages((current) => (
      current.some((item) => item.role === 'assistant' && item.text === reply)
        ? current
        : [...current, { role: 'assistant', text: reply }]
    ))
    setPreviewPlan(job.result?.preview)
    if (job.result?.preview?.requires_build) {
      setPreviewStatus('build-required')
    } else {
      setPreviewStatus('refreshing')
      setPreviewRevision((current) => current + 1)
    }
    setError('')
    forgetPendingAdaJob(jobId)
    setAdaSteps([])
    setSending(false)
    loadAdaStatus(job.conversation_id || conversationId, true)
  }, [conversationId, forgetPendingAdaJob, loadAdaStatus, t])

  useEffect(() => {
    if (!pendingAdaJob || activeAdaPollRef.current === pendingAdaJob.jobId) return
    const { jobId } = pendingAdaJob
    let cancelled = false
    let retryLogged = false
    activeAdaPollRef.current = jobId
    const poll = async () => {
      let delay = 1_000
      while (!cancelled) {
        try {
          const response = await fetchHelloAda(`/api/helloada/ada?job_id=${jobId}`, { cache: 'no-store' })
          const body = (await response.json().catch(() => ({}))) as AdaJobResponse
          if (!response.ok) {
            if (response.status >= 500 || response.status === 429) {
              throw new Error(`Ada job status returned ${response.status}`)
            }
            setError(body.error || t('error.jobStatus'))
            forgetPendingAdaJob(jobId)
            setSending(false)
            return
          }
          if (Array.isArray(body.steps)) {
            setAdaSteps(body.steps.filter((step): step is AdaJobStep => Boolean(step && typeof step.text === 'string')))
          }
          if (body.status === 'done') {
            completeAdaJob(jobId, body)
            return
          }
          if (body.status === 'error') {
            setError(t('error.adaComplete'))
            forgetPendingAdaJob(jobId)
            setAdaSteps([])
            setSending(false)
            return
          }
        } catch (cause) {
          // The job is durable and the worker may legitimately take minutes.
          // Keep polling through transient gateway/provider failures instead of
          // turning background work into a fake conversation error.
          if (!retryLogged) {
            console.warn('Ada job status temporarily unavailable', {
              jobId,
              message: cause instanceof Error ? cause.message : 'unknown error',
            })
            retryLogged = true
          }
        }
        await new Promise((resolve) => window.setTimeout(resolve, delay))
        delay = Math.min(5_000, Math.round(delay * 1.25))
      }
    }

    void poll().finally(() => {
      if (activeAdaPollRef.current === jobId) activeAdaPollRef.current = undefined
    })
    return () => {
      cancelled = true
      if (activeAdaPollRef.current === jobId) activeAdaPollRef.current = undefined
    }
  }, [completeAdaJob, forgetPendingAdaJob, pendingAdaJob, t])

  const loadActiveConversation = useCallback(() => {
    void fetchHelloAda('/api/helloada/conversations?limit=50', { cache: 'no-store' })
      .then(async (response) => {
        const body = (await response.json()) as {
          conversations?: Array<{ id?: number; archived_ts?: string | null }>
        }
        if (!response.ok) throw new Error(t('error.historyLoad'))
        const conversations = (body.conversations || []).filter((item) => typeof item.id === 'number')
        const requestedId = typeof window === 'undefined'
          ? undefined
          : Number(new URLSearchParams(window.location.search).get('conversation_id') || '')
        const savedId = typeof window === 'undefined'
          ? undefined
          : Number(window.localStorage.getItem('helloada.activeConversationId') || '')
        const active = conversations.find((item) => item.id === requestedId)
          || conversations.find((item) => item.id === savedId)
          || conversations[0]
        if (!active?.id) {
          loadAdaStatus()
          return
        }

        const detailResponse = await fetchHelloAda(`/api/helloada/conversations/${active.id}`, { cache: 'no-store' })
        const detail = (await detailResponse.json()) as {
          messages?: Array<{ role?: string; text?: string; attachments?: ChatAttachment[] }>
        }
        if (!detailResponse.ok) throw new Error(t('error.conversationRestore'))
        const restored = (detail.messages || [])
          .filter((item) => (item.role === 'user' || item.role === 'assistant') && item.text)
          .map((item) => ({
            role: item.role as 'user' | 'assistant',
            text: String(item.text),
            attachments: (item.attachments || []).filter((attachment) => attachment.asset_id !== undefined),
          }))
        setConversationId(active.id)
        if (typeof window !== 'undefined') window.localStorage.setItem('helloada.activeConversationId', String(active.id))
        setMessages(restored)
        userNearBottomRef.current = true
        lastMessageCountRef.current = 0
        scrollChatToBottom('auto')
        loadAdaStatus(active.id)
      })
      .catch(() => {
        // Conversation persistence is additive; an unavailable history endpoint
        // must not prevent the current chat bridge from working.
        loadAdaStatus()
      })
  }, [loadAdaStatus, scrollChatToBottom, t])

  useEffect(() => {
    const storedJob = readPendingAdaJob()
    const restoreTimer = storedJob
      ? window.setTimeout(() => setPendingAdaJob(storedJob), 0)
      : undefined
    loadActiveConversation()
    return () => {
      if (restoreTimer !== undefined) window.clearTimeout(restoreTimer)
    }
  }, [loadActiveConversation])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadPreviewPlan()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadPreviewPlan])

  useEffect(() => {
    if (!previewPlan?.requires_build) return
    const timer = window.setInterval(() => {
      void loadPreviewPlan()
    }, 5_000)
    return () => window.clearInterval(timer)
  }, [loadPreviewPlan, previewPlan?.requires_build])

  useEffect(() => {
    const timer = window.setInterval(() => {
      loadAdaStatus(conversationId, true, false)
    }, 30_000)
    return () => window.clearInterval(timer)
  }, [conversationId, loadAdaStatus])

  useEffect(() => {
    if (!editorOpen && !fieldEditorKey) return
    const previousOverflow = document.body.style.overflow
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (fieldEditorKey) {
        setFieldEditorKey(undefined)
        setFieldEditorEntry(undefined)
        setFieldEditorError('')
      } else {
        closeEditor()
      }
    }
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [closeEditor, editorOpen, fieldEditorKey])

  useEffect(() => {
    if (!editorOpen && !fieldEditorKey) return
    const timer = window.setTimeout(() => {
      void loadEditorMedia(1, false, editorMediaSearch)
    }, editorMediaSearch ? 240 : 0)
    return () => window.clearTimeout(timer)
  }, [editorMediaSearch, editorOpen, fieldEditorKey, loadEditorMedia])

  const handleChatScroll = useCallback(() => {
    const element = chatLogRef.current
    if (!element) return
    userNearBottomRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 72
  }, [])

  useEffect(() => {
    const element = chatLogRef.current
    if (!element) return
    const messageCountChanged = messages.length !== lastMessageCountRef.current
    const thinkingStarted = chatWorking && !previousSendingRef.current
    const initialMessagesLoaded = lastMessageCountRef.current === 0 && messages.length > 0
    if ((messageCountChanged || thinkingStarted) && (initialMessagesLoaded || userNearBottomRef.current)) {
      const prefersReducedMotion = typeof window !== 'undefined'
        && window.matchMedia('(prefers-reduced-motion: reduce)').matches
      scrollChatToBottom(prefersReducedMotion || initialMessagesLoaded ? 'auto' : 'smooth')
    }
    lastMessageCountRef.current = messages.length
    previousSendingRef.current = chatWorking
  }, [chatWorking, loading, messages.length, scrollChatToBottom])

  const uploadImages = async (files: FileList | File[]) => {
    const selected = Array.from(files).filter((file) => file.type.startsWith('image/'))
    if (!selected.length || uploadingMedia) return
    if (selected.length + pendingAttachments.length > 12) {
      setError(t('error.attachLimit'))
      return
    }
    setUploadingMedia(true)
    setError('')
    const uploaded: ChatAttachment[] = []
    try {
      for (const file of selected) {
        const form = new FormData()
        form.append('file', file)
        const response = await fetchHelloAda('/api/helloada/media/upload', { method: 'POST', body: form })
        const body = (await response.json()) as { attachment?: ChatAttachment; message?: string }
        if (!response.ok || !body.attachment?.asset_id) {
          throw new Error(body.message || t('error.imageAttach'))
        }
        uploaded.push(body.attachment)
      }
      setPendingAttachments((current) => [...current, ...uploaded])
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('error.imageAttach'))
    } finally {
      setUploadingMedia(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const sendMessage = async (preset?: string) => {
    const attachments = preset ? [] : pendingAttachments
    const text = (preset || message).trim() || (attachments.length ? 'Please review the attached images.' : '')
    if ((!text && !attachments.length) || chatWorking || uploadingMedia) return
    setSending(true)
    setError('')
    setAdaSteps([])

    try {
      const response = await fetchHelloAda('/api/helloada/ada', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          attachments: attachments.map((attachment) => ({ asset_id: attachment.asset_id })),
          conversation_id: conversationId,
          context: {
             language,
            site: workspace?.site.name || site.siteName,
            route: selectedRoute,
            collection: selectedDocument?.collection || '',
            document: selectedDocument?.sourceId || '',
            document_id: selectedDocument?.id || '',
            slug: selectedDocument?.slug || '',
             state: 'draft',
            mode: adaPhase === 'workspace' ? 'workspace' : adaPhase === 'incubation' ? 'incubation' : 'intake',
            phase: adaPhase === 'workspace' ? 'workspace' : adaPhase === 'incubation' ? 'incubation' : 'intake',
            scope: adaPhase === 'workspace' ? 'selected_page' : adaPhase === 'incubation' ? 'selected_page_reference' : 'intake',
            ...(selectedTarget ? { target: selectedTarget } : {}),
          },
        }),
      })
      const body = (await response.json()) as {
        error?: string
        message?: string
        job_id?: number
        conversation_id?: number
        mode?: AdaPhase
        phase?: AdaPhase
        website_present?: boolean
      }
      if (!response.ok) throw new Error(body.message || body.error || t('error.adaReceive'))
      if (!body.job_id) throw new Error(t('error.jobAccepted'))
      const activeConversationId = body.conversation_id || conversationId
      if (!activeConversationId) throw new Error(t('error.jobAccepted'))
      setConversationId(activeConversationId)
      if (activeConversationId && typeof window !== 'undefined') {
        window.localStorage.setItem('helloada.activeConversationId', String(activeConversationId))
      }
      setMessage('')
      setPendingAttachments([])
      setMessages((current) => [...current, { role: 'user', text, attachments }])
      if (body.phase === 'intake' || body.phase === 'incubation' || body.phase === 'workspace') {
        setAdaPhase(body.phase)
      } else if (body.mode === 'intake' || body.mode === 'incubation' || body.mode === 'workspace') {
        setAdaPhase(body.mode)
      }
      if (typeof body.website_present === 'boolean') setWebsitePresent(body.website_present)
      rememberPendingAdaJob({ jobId: body.job_id, conversationId: activeConversationId })
    } catch (cause) {
      const detail = cause instanceof Error ? cause.message : t('error.adaReceive')
      setError(detail)
      setSending(false)
    }
  }

  const sendBriefCorrection = () => {
    const correction = briefCorrection.trim()
    if (!correction || chatWorking) return
    setBriefCorrection('')
    setBriefOpen(false)
    void sendMessage(correction)
  }

  const acceptIntake = async () => {
    if (accepting || !intakeStatus?.session_id || !intakeStatus.revision || !intakeStatus.draft_hash) return
    setAccepting(true)
    setError('')
    try {
      const response = await fetchHelloAda('/api/helloada/intake/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId || intakeStatus.conversation_id,
          revision: intakeStatus.revision,
          draft_hash: intakeStatus.draft_hash,
          confirmation_text: 'I accept this working brief and want to continue with website work.',
          idempotency_key: `helloada-intake-confirm-${intakeStatus.session_id}-${intakeStatus.revision}`,
        }),
      })
      const body = (await response.json()) as IntakeStatus & { message?: string }
      if (!response.ok) throw new Error(body.message || t('error.briefAccept'))
      setIntakeStatus(body)
      setAdaPhase('workspace')
      if (body.conversation_id) setConversationId(body.conversation_id)
      setMessages((current) => [...current, {
        role: 'system',
        text: websitePresent
           ? t('workspace.briefAcceptedWebsite')
           : t('workspace.briefAcceptedFirst'),
      }])
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('error.briefAccept'))
    } finally {
      setAccepting(false)
    }
  }

  const startFirstPage = async () => {
    if (!intakeStatus?.session_id || !intakeStatus.confirmed || accepting) return
    setAccepting(true)
    setError('')
    try {
      const response = await fetchHelloAda('/api/helloada/design/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId || intakeStatus.conversation_id,
          confirmed_revision: intakeStatus.confirmed_revision_id || intakeStatus.confirmed_revision,
          owner_request: 'Start the first page design from the confirmed working brief.',
          idempotency_key: `helloada-first-page-${intakeStatus.session_id}-${intakeStatus.confirmed_revision || intakeStatus.revision}`,
        }),
      })
      const body = (await response.json()) as { message?: string; error?: string; run?: { run_id?: string } }
      if (!response.ok) throw new Error(body.message || body.error || t('error.briefStart'))
      setMessages((current) => [...current, {
        role: 'system',
        text: body.run?.run_id
           ? `${t('workspace.firstQueued')} (${body.run.run_id}).`
           : t('workspace.firstQueued'),
      }])
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('error.briefStart'))
    } finally {
      setAccepting(false)
    }
  }

  const briefSections = useMemo(() => {
    const summary = intakeStatus?.summary
    if (!summary) return []
    const sections: Array<{ key: string; title: string; entries: BriefEntry[] }> = [
      { key: 'confirmed', title: t('workspace.briefConfirmed'), entries: briefEntriesFrom(summary.confirmed) },
      { key: 'advised', title: t('workspace.briefAdvised'), entries: briefEntriesFrom(summary.advised) },
      { key: 'research', title: t('workspace.briefResearch'), entries: researchEntriesFrom(intakeStatus?.research) },
      { key: 'assumed', title: t('workspace.briefAssumptions'), entries: briefEntriesFrom(summary.assumed) },
      { key: 'open', title: t('workspace.briefOpen'), entries: [
        ...briefEntriesFrom(summary.deferred),
        ...(summary.open_topics || []).map((topic, index): BriefEntry => ({ path: `topic-${index + 1}`, value: topic })),
      ] },
    ]
    return sections.filter((section) => section.entries.length > 0)
  }, [intakeStatus?.research, intakeStatus?.summary, t])

  const editorGroups = useMemo(() => {
    const groups = new Map<string, EditablePageEntry[]>()
    for (const entry of editorEntries) {
      const section = entry.section || t('workspace.pageContent')
      groups.set(section, [...(groups.get(section) || []), entry])
    }
    return [...groups.entries()].sort(([, left], [, right]) => {
      const leftOrder = Math.min(...left.map((entry) => entry.sectionOrder ?? 999))
      const rightOrder = Math.min(...right.map((entry) => entry.sectionOrder ?? 999))
      return leftOrder - rightOrder
    })
  }, [editorEntries, t])

  const reviewEditableEntries = useMemo(
    () => reviewFields.filter((entry) => entry.editable !== false && entry.status === 'editable'),
    [reviewFields],
  )

  const pendingChangeCount = Object.keys(pendingChanges).length
  const selectedDocumentKey = selectedDocument
    ? `${selectedDocument.collection}:${selectedDocument.id}`
    : undefined
  const hasDraft = Boolean(
    selectedDocumentKey
      && (selectedDocument?.status === 'draft' || draftUpdatedKey === selectedDocumentKey),
  )

  const openFieldEditor = useCallback((key: string) => {
    const base = reviewFields.find((entry) => entry.key === key)
    const entry = pendingChangesRef.current[key] || base
    if (!entry) return
    setEditorOpen(false)
    setFieldEditorError('')
    setFieldEditorKey(key)
    setFieldEditorEntry(entry)
    setImagePickerKey(undefined)
    setEditorMedia([])
    setEditorMediaSearch('')
  }, [reviewFields])

  const closeFieldEditor = useCallback(() => {
    setFieldEditorKey(undefined)
    setFieldEditorEntry(undefined)
    setFieldEditorError('')
    setImagePickerKey(undefined)
  }, [])

  const updateFieldEditorEntry = useCallback((value: Partial<EditablePageEntry>) => {
    setFieldEditorEntry((current) => current ? { ...current, ...value } : current)
  }, [])

  const chooseFieldMedia = useCallback((value: string) => {
    const selected = editorMedia.find((media) => String(media.id) === value)
    updateFieldEditorEntry({
      image: selected
        ? {
            id: selected.id,
            sourceId: selected.sourceId || undefined,
            url: publicMediaUrl(selected),
            filename: selected.filename || undefined,
            alt: selected.alt || undefined,
          }
        : value
          ? { url: value, filename: value.split('/').pop() || 'Selected image' }
          : null,
    })
  }, [editorMedia, updateFieldEditorEntry])

  const uploadFieldImage = useCallback(async (file: File) => {
    if (!fieldEditorKey) return
    setFieldEditorError('')
    const form = new FormData()
    form.append('file', file)
    try {
      const response = await fetchHelloAda('/api/helloada/media/upload', { method: 'POST', body: form })
      const body = (await response.json()) as { attachment?: ChatAttachment; message?: string }
      const uploadedUrl = publicMediaUrl(body.attachment?.url || body.attachment?.preview_url || '', {
        id: body.attachment?.asset_id || '',
        filename: body.attachment?.name || 'image',
      })
      if (!response.ok || !body.attachment?.asset_id || !uploadedUrl) throw new Error(body.message || t('error.pageImageUpload'))
      updateFieldEditorEntry({
        image: {
          id: body.attachment.asset_id,
          sourceId: body.attachment.sourceId || undefined,
          url: uploadedUrl,
          filename: body.attachment.name || undefined,
          alt: body.attachment.alt_text || undefined,
        },
      })
      setEditorMedia((current) => [
        {
          id: body.attachment?.asset_id as string | number,
          sourceId: body.attachment?.sourceId || null,
          url: uploadedUrl || null,
          filename: body.attachment?.name || 'image',
          alt: body.attachment?.alt_text || 'HelloAda image',
        },
        ...current.filter((media) => String(media.id) !== String(body.attachment?.asset_id)),
      ])
    } catch (cause) {
      setFieldEditorError(cause instanceof Error ? cause.message : t('error.pageImageUpload'))
    }
  }, [fieldEditorKey, t, updateFieldEditorEntry])

  const applyFieldEditor = useCallback(() => {
    if (!fieldEditorKey || !fieldEditorEntry) return
    const base = reviewFields.find((entry) => entry.key === fieldEditorKey)
    if (!base) return
    setPendingChanges((current) => {
      const next = { ...current }
      if (editorEntryValue(fieldEditorEntry) === editorEntryValue(base)) delete next[fieldEditorKey]
      else next[fieldEditorKey] = fieldEditorEntry
      return next
    })
    closeFieldEditor()
  }, [closeFieldEditor, fieldEditorEntry, fieldEditorKey, reviewFields])

  const cancelPendingChanges = useCallback(() => {
    if (pendingSaving) return
    setPendingChanges({})
    closeFieldEditor()
    setPreviewStatus('refreshing')
    setPreviewRevision((current) => current + 1)
  }, [closeFieldEditor, pendingSaving])

  const updateDraft = useCallback(async () => {
    const changes = Object.values(pendingChangesRef.current)
    if (!changes.length || pendingSaving) return
    setPendingSaving(true)
    setError('')
    setFieldEditorError('')

    const contentImageChanges = changes.filter((entry) => Boolean(entry.contentEdit) && entry.type === 'image')
    const contentTextChanges = changes.filter((entry) => Boolean(entry.contentEdit) && entry.type !== 'image')

    try {
      if (contentImageChanges.length) {
        const response = await fetchHelloAda('/api/helloada/page-images', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
             publish: false,
             edits: contentImageChanges.map((entry) => ({
              ...entry.contentEdit,
              expectedValue: entry.contentEdit?.expectedValue ?? entry.value ?? '',
              newValue: editorEntryValue(entry),
            })),
          }),
        })
        const body = (await response.json()) as { message?: string }
        if (!response.ok) throw new Error(body.message || t('error.pageSave'))
      }

      if (contentTextChanges.length) {
        const response = await fetchHelloAda('/api/helloada/page-fields', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
             publish: false,
             edits: contentTextChanges.map((entry) => ({
              ...entry.contentEdit,
              expectedValue: entry.contentEdit?.expectedValue ?? entry.value ?? '',
              newValue: editorEntryValue(entry),
            })),
          }),
        })
        const body = (await response.json()) as { message?: string }
        if (!response.ok) throw new Error(body.message || t('error.pageSave'))
      }

      setPendingChanges({})
      closeFieldEditor()
      if (selectedDocumentKey) setDraftUpdatedKey(selectedDocumentKey)
      setPreviewStatus('refreshing')
      setPreviewRevision((current) => current + 1)
      const { fields } = await loadContentFields(selectedRoute)
      setReviewFields(fields)
      setEditorNotice(t('workspace.draftUpdated'))
      loadWorkspace(true)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('error.pageSave'))
    } finally {
      setPendingSaving(false)
    }
  }, [closeFieldEditor, loadContentFields, loadWorkspace, pendingSaving, selectedDocumentKey, selectedRoute, t])

  const publishDraft = useCallback(async () => {
    if (!selectedDocument || !hasDraft || pendingChangeCount || publishing) return
    setPublishing(true)
    setError('')
    setFieldEditorError('')

    try {
      const response = await fetchHelloAda('/api/helloada/publish', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          documents: [{
            collection: selectedDocument.collection,
            documentId: selectedDocument.id,
          }],
        }),
      })
       const body = (await response.json()) as { message?: string; published?: Array<{ collection?: string; documentId?: string }> }
       if (!response.ok) throw new Error(body.message || t('error.draftPublish'))

      setDraftUpdatedKey(undefined)
      setPendingChanges({})
      closeFieldEditor()
      setPreviewStatus('refreshing')
       setPreviewRevision((current) => current + 1)
       const { fields } = await loadContentFields(selectedRoute)
       setReviewFields(fields)
       setEditorNotice(t('workspace.draftPublished'))
       setPublishNotice(t('workspace.draftPublished'))
       loadWorkspace(true)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('error.draftPublish'))
    } finally {
      setPublishing(false)
    }
  }, [closeFieldEditor, hasDraft, loadContentFields, loadWorkspace, pendingChangeCount, publishing, selectedDocument, selectedRoute, t])

  const syncPreviewEditTargets = useCallback(() => {
    const frame = previewFrameRef.current
    if (!frame) return
    try {
      const document = frame.contentDocument
      if (!document) return
      // Element rectangles inside an iframe are relative to that iframe's
      // viewport, not the parent document. The overlay is sized to the same
      // inner box as the iframe, so keep these coordinates in that viewport
      // space instead of subtracting the parent frame rectangle.
      const frameWidth = frame.clientWidth
      const frameHeight = frame.clientHeight
      const overrideClaimed = new Set<Element>()
      for (const entry of reviewEditableEntries) {
        const pending = pendingChangesRef.current[entry.key]
        if (!pending) continue
        const activeElement = entry.key === activePreviewEditKeyRef.current
          && activePreviewElementRef.current?.ownerDocument === document
          && activePreviewElementRef.current?.getAttribute('data-helloada-field') === entry.key
          ? activePreviewElementRef.current
          : undefined
        const element = activeElement || previewElementForEntry(document, entry, pending, overrideClaimed)
        if (!element) continue
        overrideClaimed.add(element)
        if (pending.type === 'image' && element.tagName.toLowerCase() === 'img') {
          element.removeAttribute('srcset')
          const image = element as HTMLImageElement
          image.src = imageReferenceUrl(pending.image)
        } else {
          const nextText = editorEntryValue(pending)
          const textNode = Array.from(element.childNodes).find((node) => node.nodeType === Node.TEXT_NODE)
          if (textNode) textNode.textContent = nextText
          else element.textContent = nextText
        }
      }

      const claimed = new Set<Element>()
      const targets: PreviewEditTarget[] = []
      for (const entry of reviewEditableEntries) {
        const pending = pendingChangesRef.current[entry.key]
        const activeElement = entry.key === activePreviewEditKeyRef.current
          && activePreviewElementRef.current?.ownerDocument === document
          && activePreviewElementRef.current?.getAttribute('data-helloada-field') === entry.key
          ? activePreviewElementRef.current
          : undefined
        const element = activeElement || previewElementForEntry(document, entry, pending, claimed)
        if (!element) continue
        claimed.add(element)
        const rect = element.getBoundingClientRect()
        if (
          rect.width < 12
          || rect.height < 12
          || rect.right < 0
          || rect.bottom < 0
          || rect.left > frameWidth
          || rect.top > frameHeight
        ) continue
        targets.push({
          key: entry.key,
          label: displayEditorLabel(entry, reviewEditableEntries, reviewEditableEntries.indexOf(entry)),
          type: entry.type,
          left: Math.max(5, Math.min(frameWidth - 76, rect.right - 70)),
          top: Math.max(5, Math.min(frameHeight - 30, rect.top + 7)),
        })
      }
      setPreviewEditTargets(targets)
      if (activePreviewEditKeyRef.current && !targets.some((target) => target.key === activePreviewEditKeyRef.current)) {
        activePreviewEditKeyRef.current = undefined
        activePreviewElementRef.current = undefined
        setActivePreviewEditKey(undefined)
      }
    } catch {
      // Version-preview aliases may be cross-origin. The preview remains safe;
      // the advanced page editor is still available outside the iframe.
      setPreviewEditTargets([])
      activePreviewEditKeyRef.current = undefined
      activePreviewElementRef.current = undefined
      setActivePreviewEditKey(undefined)
    }
  }, [reviewEditableEntries])

  useEffect(() => {
    const frame = previewFrameRef.current
    if (!frame || !canEditPage) {
      const timer = window.setTimeout(() => setPreviewEditTargets([]), 0)
      return () => window.clearTimeout(timer)
    }
    let animationFrame: number | undefined
    const schedule = () => {
      if (animationFrame !== undefined) window.cancelAnimationFrame(animationFrame)
      animationFrame = window.requestAnimationFrame(() => syncPreviewEditTargets())
    }
    let observedDocument: Document | null = null
    let observedWindow: Window | null = null
    const handlePreviewPointerOver = (event: Event) => {
      const target = event.target
      if (!target || typeof target !== 'object' || (target as Node).nodeType !== 1) {
        activePreviewEditKeyRef.current = undefined
        activePreviewElementRef.current = undefined
        setActivePreviewEditKey(undefined)
        return
      }
      const elementTarget = target as Element
      const document = elementTarget.ownerDocument || observedDocument
      if (!document) {
        activePreviewEditKeyRef.current = undefined
        activePreviewElementRef.current = undefined
        setActivePreviewEditKey(undefined)
        return
      }
       const element = previewElementFromPointer(document, elementTarget)
       const imageMatch = element ? undefined : previewImageFromPointer(document, elementTarget, reviewEditableEntries)
       const activeElement = element || imageMatch?.element
       const key = element?.getAttribute('data-helloada-field') || imageMatch?.entry.key
      const active = key && reviewEditableEntries.some((entry) => entry.key === key)
         ? { key, element: activeElement }
         : undefined
      activePreviewEditKeyRef.current = active?.key
      activePreviewElementRef.current = active?.element
      setActivePreviewEditKey(active?.key)
      schedule()
    }
    const detachPreviewListeners = () => {
      observedWindow?.removeEventListener('scroll', schedule)
      observedWindow?.removeEventListener('resize', schedule)
      observedDocument?.removeEventListener('scroll', schedule, true)
      observedDocument?.removeEventListener('load', schedule, true)
      observedDocument?.removeEventListener('pointerover', handlePreviewPointerOver, true)
      observedWindow = null
      observedDocument = null
      activePreviewEditKeyRef.current = undefined
      activePreviewElementRef.current = undefined
    }
    const attachPreviewListeners = () => {
      let nextDocument: Document | null = null
      try {
        nextDocument = frame.contentDocument
      } catch {
        nextDocument = null
      }
      const nextWindow = frame.contentWindow
      if (nextDocument === observedDocument && nextWindow === observedWindow) return
      detachPreviewListeners()
      observedDocument = nextDocument
      observedWindow = nextWindow
      observedWindow?.addEventListener('scroll', schedule, { passive: true })
      observedWindow?.addEventListener('resize', schedule)
      observedDocument?.addEventListener('scroll', schedule, true)
      observedDocument?.addEventListener('load', schedule, true)
      observedDocument?.addEventListener('pointerover', handlePreviewPointerOver, true)
      schedule()
    }
    const handleFrameLoad = () => {
      attachPreviewListeners()
      schedule()
    }
    frame.addEventListener('load', handleFrameLoad)
    window.addEventListener('resize', schedule)
    attachPreviewListeners()
    const timer = window.setTimeout(schedule, 0)
    return () => {
      window.clearTimeout(timer)
      if (animationFrame !== undefined) window.cancelAnimationFrame(animationFrame)
      frame.removeEventListener('load', handleFrameLoad)
      window.removeEventListener('resize', schedule)
      detachPreviewListeners()
    }
  }, [canEditPage, pendingChangeCount, previewRevision, previewUrl, reviewEditableEntries, syncPreviewEditTargets])

  if (loading) {
    return (
      <main className="helloada-workspace helloada-workspace-loading">
        <div className="helloada-loading-mark" aria-hidden="true" />
        <p>{t('workspace.preparing')}</p>
      </main>
    )
  }

  const currentRouteLabel = routeLabel(selectedRouteData, t('workspace.home'))
  const phaseLabel = adaPhase === 'incubation'
    ? t('workspace.phaseIncubation')
    : adaPhase === 'intake'
      ? t('workspace.phaseIntake')
    : adaPhase === 'workspace'
      ? t('workspace.phaseWorkspace')
      : adaUnavailable ? t('owner.connection.unavailable') : t('workspace.phaseConnecting')
  const phaseNote = adaPhase === 'incubation'
    ? t('workspace.phaseNoteIncubation')
    : adaPhase === 'intake'
      ? t('workspace.phaseNoteIntake')
    : adaPhase === 'workspace'
      ? websitePresent
        ? t('workspace.phaseNoteWorkspace')
        : t('workspace.phaseNoteNoWebsite')
      : t('workspace.phaseNoteConnecting')
  const phaseSummary = adaPhase === 'incubation'
    ? t('workspace.phaseSummaryIncubation')
    : adaPhase === 'intake'
      ? t('workspace.phaseSummaryIntake')
    : adaPhase === 'workspace'
      ? websitePresent
        ? t('workspace.phaseSummaryWorkspace')
        : t('workspace.phaseSummaryNoWebsite')
      : adaUnavailable ? t('owner.reconnectNote') : t('workspace.phaseSummaryConnecting')
  const shortcuts = adaPhase === 'intake' || adaPhase === 'incubation'
    ? [[t('workspace.shortClarify'), t('workspace.shortClarifyPrompt')]]
    : [
        [t('owner.improvePage'), t('owner.improvePrompt')],
        [t('owner.writeUpdate'), t('workspace.shortDraftPrompt')],
        [t('owner.newPage'), t('workspace.shortStartPagePrompt')],
      ]
  const canAcceptIntake = (adaPhase === 'intake' || adaPhase === 'incubation')
    && intakeStatus?.readiness?.state === 'ready_to_build'
    && Boolean(intakeStatus.draft_hash && intakeStatus.revision)
  const canStartFirstPage = !websitePresent
    && adaPhase === 'workspace'
    && Boolean(intakeStatus?.confirmed && intakeStatus.session_id)
  const hasBrief = briefSections.length > 0
  const adaProgressSteps = (() => {
    const seen = new Set<string>()
    const steps: AdaJobStep[] = []
    for (const step of adaSteps) {
      const text = step.text?.trim()
      if (!text) continue
      const key = text.toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      steps.push({ ...step, text })
    }
    return steps.slice(-8)
  })()
  const currentAdaProgress = adaProgressSteps[adaProgressSteps.length - 1]?.text || t('workspace.thinking')
  return (
    <main className={`helloada-workspace helloada-owner-workspace shows-${mobilePane}`}>
      {error ? <div className="helloada-alert" role="alert">{error}</div> : null}
      {websitePresent ? <div className="helloada-pane-switch" role="group" aria-label={t('owner.workspace')}>
        <button type="button" id="helloada-ada-tab" aria-controls="helloada-ada-pane" aria-pressed={mobilePane === 'ada'} onClick={() => setMobilePane('ada')}>{t('workspace.askAda')}</button>
        <button type="button" id="helloada-website-tab" aria-controls="helloada-website-pane" aria-pressed={mobilePane === 'website'} onClick={() => setMobilePane('website')}>{t('owner.website')}{hasDraft ? <i aria-label={t('owner.readyReview')} /> : null}</button>
      </div> : null}
       <div className={`helloada-workspace-grid ${websitePresent ? '' : 'is-chat-only'}`}>
         {websitePresent ? <section id="helloada-website-pane" className="helloada-review-window" aria-label={t('workspace.websiteReview')}>
          <div className="helloada-review-toolbar">
            <div className="helloada-window-dots" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <div className="helloada-window-title">
              <span>{t('owner.website')}</span>
            </div>
             <div className="helloada-segmented" role="group" aria-label={t('workspace.previewViewport')}>
               <button
                 className={previewViewport === 'mobile' ? 'is-selected' : ''}
                 type="button"
                 onClick={() => setPreviewViewport('mobile')}
                 aria-label={t('workspace.previewMobile')}
                 title={t('workspace.previewMobile')}
                 aria-pressed={previewViewport === 'mobile'}
               >
                 <WorkspaceIcon name="mobile" size={16} />
               </button>
               <button
                 className={previewViewport === 'tablet' ? 'is-selected' : ''}
                 type="button"
                 onClick={() => setPreviewViewport('tablet')}
                 aria-label={t('workspace.previewTablet')}
                 title={t('workspace.previewTablet')}
                 aria-pressed={previewViewport === 'tablet'}
               >
                 <WorkspaceIcon name="tablet" size={16} />
               </button>
               <button
                 className={previewViewport === 'desktop' ? 'is-selected' : ''}
                 type="button"
                 onClick={() => setPreviewViewport('desktop')}
                 aria-label={t('workspace.previewDesktop')}
                 title={t('workspace.previewDesktop')}
                 aria-pressed={previewViewport === 'desktop'}
               >
                 <WorkspaceIcon name="desktop" size={16} />
               </button>
            </div>
            <label className="helloada-page-control">
               <span className="helloada-sr-only">{t('workspace.visiblePage')}</span>
                  <select aria-label={t('workspace.visiblePage')} value={selectedRoute} disabled={adaPhase === 'intake' || adaPhase === 'unknown'} onChange={(event) => {
                    setPreviewStatus('refreshing')
                    setSelectedRoute(event.target.value)
                  }}>
                {(workspace?.routes || []).map((route) => (
                  <option key={`${route.path}:${route.sourceId}`} value={route.path}>
                     {routeLabel(route, t('workspace.home'))}
                  </option>
                ))}
              </select>
            </label>
              {canEditPage ? <details className="helloada-preview-options">
                <summary aria-label={t('owner.pageOptions')} title={t('owner.pageOptions')}><WorkspaceIcon name="settings" /></summary>
                <div><button type="button" onClick={() => void openEditor()}>{t('owner.editManually')}</button><label><input type="checkbox" checked={manualEditing} onChange={(event) => setManualEditing(event.target.checked)} />{t('owner.quickEditing')}</label></div>
              </details> : null}
            </div>
            {pendingChangeCount || hasDraft || publishNotice ? <div className="helloada-review-decision" role="status">
               {pendingChangeCount ? (
                 <div className="helloada-draft-actions" aria-label={t('workspace.draftActions')}>
                   <span>{pendingChangeCount} {t('workspace.pendingChanges')}</span>
                   <button type="button" onClick={() => void updateDraft()} disabled={pendingSaving}>
                     {pendingSaving ? t('workspace.updatingDraft') : t('workspace.updateDraft')}
                   </button>
                   <button type="button" className="is-quiet" onClick={cancelPendingChanges} disabled={pendingSaving}>
                     {t('workspace.cancelChanges')}
                   </button>
                 </div>
               ) : null}
                {hasDraft && !pendingChangeCount ? (
                  <button
                   className="helloada-draft-action is-publish"
                   type="button"
                   onClick={() => publishDialogRef.current?.showModal()}
                   disabled={publishing}
                 >
                   {publishing ? t('workspace.publishingDraft') : t('owner.publishChanges')}
                  </button>
                ) : null}
                {publishNotice ? <p className="helloada-draft-confirmation" role="status" aria-live="polite">{publishNotice}</p> : null}
             </div> : null}

             <div className={`helloada-preview-frame-shell is-${previewViewport}`}>
               <iframe
                 ref={previewFrameRef}
                 key={`${previewUrl}:${previewRevision}`}
                 className="helloada-preview-frame"
                 title={t('workspace.previewTitle')}
                 src={previewUrl}
                 onLoad={handlePreviewLoad}
                 onError={() => setPreviewStatus('error')}
               />
               {previewStatusMessage ? (
                 <div
                   className={`helloada-preview-status is-${previewStatus}`}
                   role="status"
                   aria-live="polite"
                 >
                   {previewStatus === 'refreshing' ? <span className="helloada-preview-status-spinner" aria-hidden="true" /> : null}
                   <span>{previewStatusMessage}</span>
                 </div>
               ) : null}
               {manualEditing && activePreviewEditKey && previewEditTargets.some((target) => target.key === activePreviewEditKey) ? (
                <div className="helloada-preview-edit-overlay" role="group" aria-label={t('workspace.quickEditLabel')}>
                  {previewEditTargets.filter((target) => target.key === activePreviewEditKey).map((target) => (
                    <button
                      key={target.key}
                      type="button"
                      style={{ left: target.left, top: target.top }}
                      aria-label={`${t('workspace.quickEditButton')}: ${target.label}`}
                      onClick={() => openFieldEditor(target.key)}
                    >
                      {target.type === 'image' ? t('workspace.quickEditButton') : t('workspace.quickEditFieldButton')}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          <footer className="helloada-preview-footer"><span className={hasDraft ? 'is-draft' : ''}><i aria-hidden="true" />{hasDraft ? t('owner.readyReview') : t('owner.websitePreview')}</span><span>{hasDraft ? t('owner.notLive') : t('owner.previewHint')}</span></footer>
        </section> : null}

         <aside id="helloada-ada-pane" className="helloada-ada-panel" aria-label={t('workspace.adaAssistant')}>
           <div className="helloada-panel-header">
             <div className="helloada-assistant-identity">
                <HelloAdaMark size={32} />
                <div><strong>Ada</strong><span>{t('owner.assistantRole')}</span></div>
             </div>
             <div className="helloada-panel-header-actions">
               {adaPhase === 'workspace' ? (
                 <button
                   className="helloada-new-chat"
                   type="button"
                   onClick={startNewChat}
                   disabled={chatWorking}
                 >
                   <WorkspaceIcon name="plus" size={14} /> {t('workspace.newChat')}
                 </button>
               ) : null}
             </div>
           </div>

          <div className="helloada-chat-context">
             <span>{t('workspace.workingOn')}</span>
            <strong>{currentRouteLabel}</strong>
             {hasBrief ? <button className="helloada-context-button" type="button" aria-expanded={briefOpen} aria-controls="helloada-working-brief" onClick={() => setBriefOpen((current) => !current)}>{t('owner.businessContext')}</button> : null}
          </div>

           {adaPhase !== 'workspace' || !websitePresent ? <div className={`helloada-phase-bar is-${adaPhase}`} role="status">
             <span className="helloada-phase-mark" aria-hidden="true" />
             <div className="helloada-phase-copy">
               <strong>{phaseLabel}</strong>
               <span>{phaseSummary}</span>
               <span className="helloada-sr-only">{phaseNote}</span>
             </div>
             <div className="helloada-phase-actions">
               {hasBrief && adaPhase !== 'workspace' ? (
                 <button
                   className="helloada-phase-action"
                   type="button"
                   aria-expanded={briefOpen}
                   aria-controls="helloada-working-brief"
                   onClick={() => setBriefOpen((current) => !current)}
                 >
                   {briefOpen ? t('workspace.closeBrief') : t('workspace.viewBrief')}
                 </button>
               ) : null}
               {canAcceptIntake ? (
                 <button className="helloada-phase-action is-primary" type="button" onClick={() => void acceptIntake()} disabled={accepting}>
                   {accepting ? t('workspace.accepting') : t('workspace.acceptBrief')}
                 </button>
               ) : null}
               {canStartFirstPage ? (
                 <button className="helloada-phase-action is-primary" type="button" onClick={() => void startFirstPage()} disabled={accepting}>
                   {accepting ? t('workspace.starting') : t('workspace.startFirstPage')}
                 </button>
               ) : null}
               {adaUnavailable ? <button className="helloada-phase-action" type="button" onClick={() => loadAdaStatus(conversationId)}>{t('owner.retry')}</button> : null}
             </div>
           </div> : null}

           {briefOpen && hasBrief ? (
             <section className="helloada-brief-inspector" id="helloada-working-brief" aria-label={t('workspace.briefTitle')}>
               <div className="helloada-brief-inspector-header">
                 <div>
                   <p className="helloada-eyebrow">{t('workspace.briefLabel')}</p>
                   <strong>{t('workspace.briefTitle')}</strong>
                 </div>
                 <button type="button" aria-label={t('workspace.closeBrief')} onClick={() => setBriefOpen(false)}>×</button>
               </div>
               <p className="helloada-brief-intro">{t('workspace.briefIntro')}</p>
               <div className="helloada-brief-sections">
                 {briefSections.map((section) => (
                   <section className="helloada-brief-section" key={section.key}>
                     <h3>{section.title}</h3>
                     <div className="helloada-brief-entries">
                       {section.entries.map((entry) => (
                         <div className="helloada-brief-entry" key={`${section.key}-${entry.path}`}>
                           <div>
                             <strong>{briefPathLabel(entry.path)}</strong>
                             {entry.note ? <small>{entry.note}</small> : null}
                           </div>
                           <span>{briefValueLabel(entry.value)}</span>
                         </div>
                       ))}
                     </div>
                   </section>
                 ))}
               </div>
               <form
                 className="helloada-brief-correction"
                 onSubmit={(event) => {
                   event.preventDefault()
                   sendBriefCorrection()
                 }}
               >
                 <label htmlFor="helloada-brief-correction">{t('workspace.briefCorrection')}</label>
                 <textarea
                   id="helloada-brief-correction"
                   value={briefCorrection}
                   onChange={(event) => setBriefCorrection(event.target.value)}
                   placeholder={t('workspace.briefCorrectionPlaceholder')}
                   rows={2}
                    disabled={chatWorking}
                 />
                  <button type="submit" disabled={chatWorking || !briefCorrection.trim()}>
                   {t('workspace.sendCorrection')}
                 </button>
               </form>
             </section>
           ) : null}

           <div className="helloada-chat-log" ref={chatLogRef} onScroll={handleChatScroll} aria-live="polite">
             {!messages.length ? <div className="helloada-owner-welcome"><HelloAdaMark size={54} /><h2>{websitePresent ? t('owner.welcome') : t('owner.welcomeNew')}</h2><p>{websitePresent ? t('owner.welcomeNote') : t('workspace.tellAdaIntake')}</p></div> : null}
            {messages.map((item, index) => (
              <div className={`helloada-chat-message is-${item.role}`} key={`${item.role}-${index}`}>
                 <span>{item.role === 'assistant' ? t('workspace.roleAda') : item.role === 'user' ? t('workspace.roleYou') : t('workspace.roleStudio')}</span>
                {item.attachments?.length ? (
                   <div className="helloada-chat-attachments" aria-label={t('workspace.attachedImages')}>
                    {item.attachments.map((attachment, attachmentIndex) => {
                      const source = attachment.thumbnail_url || attachment.preview_url || attachment.url || ''
                      return (
                        <figure className="helloada-chat-attachment" key={`${attachment.asset_id || 'attachment'}-${attachmentIndex}`}>
                           {source ? <Image src={source} alt={attachment.alt_text || attachment.name || t('workspace.image')} width={92} height={70} unoptimized /> : <span className="helloada-chat-attachment-placeholder">{t('workspace.image')}</span>}
                          <figcaption>
                            <strong>{attachment.name || `${t('workspace.image')} ${attachmentIndex + 1}`}</strong>
                            {attachment.analysis_error
                               ? <small className="is-error">{t('workspace.analysisUnavailable')}</small>
                              : attachment.analysis_status
                                ? <small>{attachment.analysis_status}</small>
                                : null}
                          </figcaption>
                        </figure>
                      )
                    })}
                  </div>
                ) : null}
                 <HelloAdaChatMessage text={item.text} />
               </div>
             ))}
              {chatWorking ? (
                <div className="helloada-chat-thinking" role="status" aria-label={t('workspace.thinking')}>
                  <div className="helloada-chat-thinking-current">
                    <span>{currentAdaProgress}</span>
                    <i aria-hidden="true"><b /><b /><b /></i>
                  </div>
                   {adaProgressSteps.length > 1 ? (
                     <details className="helloada-chat-progress"><summary>{t('owner.seeProgress')}</summary>
                       {adaProgressSteps.map((step, index) => (
                         <span key={`${step.ts || step.text}-${index}`} className={index === adaProgressSteps.length - 1 ? 'is-current' : 'is-complete'}>
                           <b aria-hidden="true">{index === adaProgressSteps.length - 1 ? '•' : '✓'}</b>
                           {step.text}
                         </span>
                       ))}
                    </details>
                  ) : null}
                </div>
              ) : null}
           </div>

          {adaPhase === 'workspace' && workspace?.documents.length === 0 ? (
            <div className="helloada-context-note" role="status">
               <strong>{t('workspace.contextConnected')}</strong>
               <p>{t('workspace.contextConnectedNote')}</p>
            </div>
          ) : null}

           <div className="helloada-shortcuts" aria-label={t('workspace.quickActions')}>
            {shortcuts.map(([label, prompt]) => (
              <button key={label} type="button" onClick={() => { setMessage(prompt); setMobilePane('ada'); window.setTimeout(() => messageInputRef.current?.focus(), 0) }} disabled={chatWorking}>
                {label}
              </button>
            ))}
          </div>

           <form
             className="helloada-chat-form"
             noValidate
             onSubmit={(event) => {
               event.preventDefault()
               event.stopPropagation()
               void sendMessage()
             }}
           >
             <label className="helloada-sr-only" htmlFor="helloada-ada-message">{t('workspace.askAda')}</label>
            {pendingAttachments.length ? (
               <div className="helloada-pending-attachments" aria-label={t('workspace.pendingAttachments')}>
                {pendingAttachments.map((attachment, index) => {
                  const source = attachment.thumbnail_url || attachment.preview_url || attachment.url || ''
                  return (
                    <button
                      className="helloada-pending-attachment"
                      key={`${attachment.asset_id || 'pending'}-${index}`}
                      type="button"
                       aria-label={`${t('workspace.removeImage')} ${attachment.name || `${t('workspace.image')} ${index + 1}`}`}
                      onClick={() => setPendingAttachments((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                    >
                       {source ? <Image src={source} alt="" width={46} height={46} unoptimized /> : <span>{t('workspace.image')}</span>}
                      <b aria-hidden="true">×</b>
                    </button>
                  )
                })}
              </div>
            ) : null}
            <div className="helloada-chat-input-shell">
              <input
                ref={fileInputRef}
                className="helloada-file-input"
                type="file"
                accept="image/*"
                multiple
                onChange={(event) => {
                  if (event.target.files) void uploadImages(event.target.files)
                }}
              />
               <textarea
                 ref={messageInputRef}
                 id="helloada-ada-message"
                value={message}
               onChange={(event) => setMessage(event.target.value)}
                 onKeyDown={(event) => {
                   if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && adaPhase !== 'unknown') {
                     event.preventDefault()
                     void sendMessage()
                   }
                 }}
                  placeholder={adaPhase === 'intake' || adaPhase === 'incubation' ? t('workspace.tellAdaIntake') : t('workspace.describeNextChange')}
                rows={2}
                 disabled={chatWorking}
              />
              <button
                className="helloada-attach-button"
                type="button"
                onClick={() => fileInputRef.current?.click()}
                 disabled={chatWorking || uploadingMedia}
                 aria-label={uploadingMedia ? t('workspace.attachingImage') : t('workspace.attachImages')}
              >
                {uploadingMedia ? '…' : <WorkspaceIcon name="plus" />}
              </button>
               <button
                 className="helloada-send-button"
                 type="button"
                 onClick={() => void sendMessage()}
                  disabled={adaPhase === 'unknown' || chatWorking || uploadingMedia || (!message.trim() && !pendingAttachments.length)}
                  aria-label={t('workspace.send')}
               >
                <WorkspaceIcon name="arrow" />
              </button>
            </div>
            <p className="helloada-composer-note">{t('owner.composerNote')}</p>
          </form>
         </aside>
       </div>

       <dialog ref={publishDialogRef} className="helloada-publish-dialog" aria-labelledby="helloada-publish-title">
         <HelloAdaMark size={40} /><h2 id="helloada-publish-title">{t('owner.publishTitle')}</h2><p><strong>{currentRouteLabel}</strong> · {site.siteName}</p><p>{t('owner.publishNote')}</p>
         <div><button type="button" autoFocus onClick={() => publishDialogRef.current?.close()}>{t('owner.keepReviewing')}</button><button type="button" className="is-primary" disabled={!hasDraft || publishing || Boolean(pendingChangeCount)} onClick={() => { publishDialogRef.current?.close(); void publishDraft() }}>{t('owner.publishChanges')}<WorkspaceIcon name="arrow" /></button></div>
       </dialog>

        {fieldEditorEntry && fieldEditorKey ? (
          <div className="helloada-field-popover-backdrop" role="presentation">
            <section className="helloada-field-popover" role="dialog" aria-modal="true" aria-labelledby="helloada-field-popover-title">
              <header className="helloada-field-popover-header">
                <div>
                  <p className="helloada-eyebrow">{t('workspace.fieldEditorLabel')}</p>
                  <h2 id="helloada-field-popover-title">{fieldEditorEntry.label}</h2>
                  <small>{fieldEditorEntry.section || t('workspace.pageContent')}</small>
                </div>
                <button type="button" aria-label={t('workspace.pageClose')} onClick={closeFieldEditor}>×</button>
              </header>
              {fieldEditorError ? <p className="helloada-page-editor-message is-error" role="alert">{fieldEditorError}</p> : null}
              {fieldEditorEntry.type === 'text' || fieldEditorEntry.type === 'link' ? (
                <textarea
                  className="helloada-field-popover-textarea"
                  value={fieldEditorEntry.text || ''}
                  onChange={(event) => updateFieldEditorEntry({ text: event.target.value })}
                  rows={fieldEditorEntry.type === 'link' ? 2 : 5}
                  autoFocus
                />
              ) : fieldEditorEntry.type === 'richText' ? (
                <EditableRichTextEditor
                  key={fieldEditorKey}
                  value={fieldEditorEntry.richText}
                  onChange={(value) => updateFieldEditorEntry({ richText: value, text: sourceTextForRichText(value) })}
                  placeholder={t('workspace.pageRichTextPlaceholder')}
                />
              ) : (
                <div className="helloada-field-popover-image">
                  <div className={`helloada-page-editor-image-preview ${imageReferenceUrl(fieldEditorEntry.image) ? '' : 'is-empty'}`}>
                    {imageReferenceUrl(fieldEditorEntry.image)
                      ? <AdminMediaThumbnail src={imageReferenceUrl(fieldEditorEntry.image)} alt={imageReferenceLabel(fieldEditorEntry.image) || fieldEditorEntry.label} width={220} height={160} unavailableLabel={t('workspace.pageGalleryUnavailable')} />
                      : <span>{t('workspace.pageNoImage')}</span>}
                  </div>
                  <div className="helloada-field-popover-image-actions">
                    <button type="button" onClick={() => setImagePickerKey((current) => current === fieldEditorKey ? undefined : fieldEditorKey)}>
                      {imagePickerKey === fieldEditorKey ? t('workspace.pageGalleryHide') : t('workspace.pageGalleryBrowse')}
                    </button>
                    <button type="button" onClick={() => fieldImageInputRef.current?.click()}>{t('workspace.pageUploadImage')}</button>
                    {imageReferenceUrl(fieldEditorEntry.image) ? (
                      <button type="button" className="is-quiet" onClick={() => updateFieldEditorEntry({ image: null })}>{t('workspace.pageRemoveImage')}</button>
                    ) : null}
                  </div>
                  {imagePickerKey === fieldEditorKey ? (
                    <div className="helloada-field-popover-gallery">
                      {editorMediaLoading && !editorMedia.length ? <p>{t('workspace.pageGalleryLoading')}</p> : null}
                      {editorMedia.length ? editorMedia.map((media) => {
                        const mediaId = String(media.id)
                        const selected = imageReferenceId(fieldEditorEntry.image) === mediaId
                        return (
                          <button
                            type="button"
                            key={mediaId}
                            className={selected ? 'is-selected' : ''}
                            onClick={() => chooseFieldMedia(mediaId)}
                          >
                            <AdminMediaThumbnail src={publicMediaUrl(media)} alt={media.alt || media.filename || mediaId} width={84} height={64} unavailableLabel={t('workspace.pageGalleryUnavailable')} />
                            <span>{media.filename || media.alt || mediaId}</span>
                          </button>
                        )
                      }) : null}
                    </div>
                  ) : null}
                  <input
                    ref={fieldImageInputRef}
                    className="helloada-file-input"
                    type="file"
                    accept="image/*"
                    onChange={(event) => {
                      const file = event.target.files?.[0]
                      if (file) void uploadFieldImage(file)
                      event.target.value = ''
                    }}
                  />
                </div>
              )}
              <footer className="helloada-field-popover-footer">
                <button type="button" className="helloada-page-editor-cancel" onClick={closeFieldEditor}>{t('workspace.pageClose')}</button>
                <button type="button" className="helloada-page-editor-save" onClick={applyFieldEditor}>{t('workspace.applyFieldChange')}</button>
              </footer>
            </section>
          </div>
        ) : null}

        {editorOpen ? (
         <div className="helloada-editor-backdrop" role="presentation">
           <section className="helloada-page-editor" role="dialog" aria-modal="true" aria-labelledby="helloada-page-editor-title">
             <header className="helloada-page-editor-header">
               <div>
                 <p className="helloada-eyebrow">{t('workspace.pageEditorLabel')}</p>
                 <h2 id="helloada-page-editor-title">{editorPage?.title || currentRouteLabel}</h2>
                 <p>{t('workspace.pageEditorIntro')}</p>
               </div>
               <button className="helloada-page-editor-close" type="button" onClick={closeEditor} aria-label={t('workspace.pageClose')}>×</button>
             </header>

             {editorLoading ? (
               <div className="helloada-page-editor-loading" role="status">
                 <span className="helloada-loading-mark" aria-hidden="true" />
                 <p>{t('workspace.pageLoading')}</p>
               </div>
             ) : (
               <>
                 {editorError ? <p className="helloada-page-editor-message is-error" role="alert">{editorError}</p> : null}
                 <div className="helloada-page-editor-scroll">
                   {editorGroups.length ? editorGroups.map(([section, entries]) => (
                     <section className="helloada-page-editor-section" key={section}>
                       <div className="helloada-page-editor-section-heading">
                         <span>{section}</span>
                         <small>{entries.length} {entries.length === 1 ? t('workspace.pageFieldSingular') : t('workspace.pageFieldPlural')}</small>
                       </div>
                       <div className="helloada-page-editor-fields">
                          {entries.map((entry, entryIndex) => {
                             const inputId = `helloada-editable-${entry.key.replace(/[^a-z0-9]+/gi, '-')}`
                             const displayLabel = displayEditorLabel(entry, entries, entryIndex)
                            const selectedImageId = imageReferenceId(entry.image)
                            const selectedMedia = editorMedia.find((media) => String(media.id) === selectedImageId)
                            const previewSource = imageReferenceUrl(entry.image) || selectedMedia?.url || ''
                            const selectedImageValue = selectedImageId || previewSource
                            return (
                               <article className="helloada-page-editor-field" key={entry.key}>
                                <div className="helloada-page-editor-field-heading">
                                   <label htmlFor={entry.type === 'text' || entry.type === 'link' ? inputId : undefined}>{displayLabel}</label>
                                   <span>{editorRoleLabel(entry)}</span>
                                </div>
                                {entry.type === 'text' || entry.type === 'link' ? (
                                  <textarea
                                    id={inputId}
                                    value={entry.text || ''}
                                    disabled={entry.editable === false}
                                    onChange={(event) => updateEditorEntry(entry.key, { text: event.target.value })}
                                    rows={3}
                                 />
                               ) : entry.type === 'richText' ? (
                                  <EditableRichTextEditor
                                    key={`${entry.key}:${editorPage?.id || 'page'}`}
                                    value={entry.richText}
                                    onChange={(value) => updateEditorEntry(entry.key, { richText: value, text: sourceTextForRichText(value) })}
                                    placeholder={t('workspace.pageRichTextPlaceholder')}
                                  />
                                 ) : (
                                  <div className="helloada-page-editor-image-field">
                                    <div className={`helloada-page-editor-image-preview ${previewSource ? '' : 'is-empty'}`}>
                                       {previewSource ? <AdminMediaThumbnail src={previewSource} alt={imageReferenceLabel(entry.image) || selectedMedia?.alt || displayLabel} width={128} height={112} unavailableLabel={t('workspace.pageGalleryUnavailable')} /> : <span>{t('workspace.pageNoImage')}</span>}
                                    </div>
                                    <div className="helloada-page-editor-image-controls">
                                      <div className="helloada-page-editor-image-toolbar">
                                        <span>{t('workspace.pageChooseImage')}</span>
                                        <button
                                          type="button"
                                          className="helloada-page-editor-gallery-toggle"
                                          aria-expanded={imagePickerKey === entry.key}
                                          onClick={() => setImagePickerKey((current) => current === entry.key ? undefined : entry.key)}
                                        >
                                          {imagePickerKey === entry.key ? t('workspace.pageGalleryHide') : t('workspace.pageGalleryBrowse')}
                                        </button>
                                      </div>
                                      {imagePickerKey === entry.key ? (
                                        <div className="helloada-page-editor-gallery">
                                          <div className="helloada-page-editor-gallery-header">
                                            <label htmlFor={`${inputId}-search`}>{t('workspace.pageGallerySearchLabel')}</label>
                                            <input
                                              id={`${inputId}-search`}
                                              type="search"
                                              value={editorMediaSearch}
                                              onChange={(event) => setEditorMediaSearch(event.target.value)}
                                              placeholder={t('workspace.pageGallerySearchPlaceholder')}
                                            />
                                          </div>
                                          {editorMediaLoading && !editorMedia.length ? (
                                            <p className="helloada-page-editor-gallery-status">{t('workspace.pageGalleryLoading')}</p>
                                          ) : editorMedia.length ? (
                                            <>
                                              <div className="helloada-page-editor-gallery-grid" role="listbox" aria-label="Image gallery">
                                                {editorMedia.map((media) => {
                                                  const mediaId = String(media.id)
                                                  const mediaUrl = publicMediaUrl(media)
                                                  const selected = selectedImageId === mediaId
                                                  const mediaLabel = media.sourcePages?.[0] ? imageReferenceLabel({ filename: media.sourcePages[0] }) : media.alt || media.filename || `Image ${media.id}`
                                                  return (
                                                    <button
                                                      key={mediaId}
                                                      type="button"
                                                      role="option"
                                                      aria-selected={selected}
                                                      className={`helloada-page-editor-gallery-item ${selected ? 'is-selected' : ''}`}
                                                      onClick={() => chooseEditorMedia(entry.key, mediaId)}
                                                    >
                                                      <span className="helloada-page-editor-gallery-thumb">
                                                        <AdminMediaThumbnail src={mediaUrl} alt={media.alt || mediaLabel} width={120} height={92} unavailableLabel={t('workspace.pageGalleryUnavailable')} />
                                                      </span>
                                                      <span className="helloada-page-editor-gallery-caption">{mediaLabel}</span>
                                                    </button>
                                                  )
                                                })}
                                              </div>
                                              {editorMediaHasNext ? (
                                                <button
                                                  type="button"
                                                  className="helloada-page-editor-gallery-more"
                                                  onClick={() => void loadEditorMedia(editorMedia.length / 72 + 1, true, editorMediaSearch)}
                                                  disabled={editorMediaLoading}
                                                >
                                                  {editorMediaLoading ? t('workspace.pageGalleryLoading') : t('workspace.pageGalleryMore')}
                                                </button>
                                              ) : null}
                                            </>
                                          ) : (
                                            <p className="helloada-page-editor-gallery-status">{t('workspace.pageGalleryNoMatch')}</p>
                                          )}
                                        </div>
                                      ) : null}
                                      <div className="helloada-page-editor-image-actions">
                                        <button
                                         type="button"
                                         onClick={() => {
                                           editorImageTargetRef.current = entry.key
                                           editorImageInputRef.current?.click()
                                         }}
                                       >
                                         {t('workspace.pageUploadImage')}
                                       </button>
                                         {selectedImageValue ? (
                                          <button type="button" className="is-quiet" onClick={() => updateEditorEntry(entry.key, { image: null })}>
                                           {t('workspace.pageRemoveImage')}
                                         </button>
                                       ) : null}
                                     </div>
                                   </div>
                                 </div>
                               )}
                             </article>
                           )
                         })}
                       </div>
                     </section>
                   )) : (
                     <div className="helloada-page-editor-message">{t('workspace.pageNoEditableContent')}</div>
                   )}
                 </div>
                 <input
                   ref={editorImageInputRef}
                   className="helloada-file-input"
                   type="file"
                   accept="image/*"
                   onChange={(event) => {
                     const file = event.target.files?.[0]
                     const key = editorImageTargetRef.current
                     if (file && key) void uploadEditorImage(file, key)
                     event.target.value = ''
                   }}
                 />
                 {editorNotice ? <p className="helloada-page-editor-notice" role="status">{editorNotice}</p> : null}
                 {editorError ? <p className="helloada-page-editor-message is-error" role="alert">{editorError}</p> : null}
                   <footer className="helloada-page-editor-footer">
                     <span>{t('workspace.pageDraftNote')}</span>
                    <div>
                      <button type="button" className="helloada-page-editor-cancel" onClick={closeEditor} disabled={editorSaving}>{t('workspace.pageClose')}</button>
                       <button type="button" className="helloada-page-editor-save" onClick={saveEditor} disabled={editorSaving || editorLoading || !editorPage}>
                        {editorSaving ? t('workspace.pageSaving') : t('workspace.applyFieldChange')}
                     </button>
                   </div>
                 </footer>
               </>
             )}
           </section>
         </div>
       ) : null}
      </main>
  )
}
