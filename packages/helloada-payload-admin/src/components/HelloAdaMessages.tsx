'use client'

import Link from 'next/link'
import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchHelloAda } from '../api/fetchHelloAda'
import { useHelloAdaTranslations } from '../api/useHelloAdaTranslations'
import { WorkspaceIcon } from './WorkspaceIcon'

type Contact = { id: string | number; name?: string; email: string; phone?: string; company?: string; notes?: string; source?: string; lastSeenAt?: string }
type Conversation = {
  id: string | number
  subject?: string
  state: 'needs_reply' | 'done' | 'archived' | 'spam'
  unread?: boolean
  source?: 'form' | 'email'
  lastActivityAt?: string
  lastMessagePreview?: string
  participantEmail?: string
  contact?: Contact | string | number
}
type Message = {
  id: string | number
  direction: 'form_enquiry' | 'received_email' | 'reply'
  from: string
  to?: string
  subject: string
  text: string
  draftText?: string
  draftRevision?: number
  deliveryState?: string
  createdAt?: string
  attachmentManifest?: Array<{ index: number; filename: string; mimeType: string; size: number; allowed: boolean }>
}
type Mailbox = {
  address?: string
  domain?: string
  state: string
  statusDetail?: string
  notificationAddress?: string
  notificationVerifiedAt?: string
  notificationPendingAddress?: string
  notificationCodeExpiresAt?: string
}
type ResponseData = { conversations?: Conversation[]; contacts?: Contact[]; conversation?: Conversation; messages?: Message[]; mailbox?: Mailbox }

const contactOf = (value: Conversation['contact']): Contact | undefined =>
  value && typeof value === 'object' ? value as Contact : undefined

export function HelloAdaMessages() {
  const { t } = useHelloAdaTranslations()
  const [tab, setTab] = useState<'inbox' | 'contacts'>('inbox')
  const [filter, setFilter] = useState<'needs_reply' | 'all' | 'done' | 'archived' | 'spam'>('needs_reply')
  const [search, setSearch] = useState('')
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [contacts, setContacts] = useState<Contact[]>([])
  const [activeId, setActiveId] = useState<string>()
  const [activeContactId, setActiveContactId] = useState<string>()
  const [detail, setDetail] = useState<ResponseData>()
  const [mailbox, setMailbox] = useState<Mailbox>()
  const [notificationAddress, setNotificationAddress] = useState('')
  const [notificationCode, setNotificationCode] = useState('')
  const [savingNotification, setSavingNotification] = useState(false)
  const [draft, setDraft] = useState('')
  const [draftHash, setDraftHash] = useState('')
  const [draftRevision, setDraftRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [draftingWithAda, setDraftingWithAda] = useState(false)
  const [sending, setSending] = useState(false)
  const [confirmSend, setConfirmSend] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const sendRequestRef = useRef<{ draftHash: string; requestId: string } | undefined>(undefined)
  const draftDirtyRef = useRef(false)
  const notificationAddressTouched = useRef(false)
  const [deepLinkConversation, setDeepLinkConversation] = useState('')
  const [sessionAvailable, setSessionAvailable] = useState(true)

  const load = useCallback(async (quiet = false) => {
    if (!quiet) { setLoading(true); setError('') }
    try {
      const query = new URLSearchParams({ view: tab, state: filter })
      if (search.trim()) query.set('q', search.trim())
      if (deepLinkConversation) query.set('conversation', deepLinkConversation)
      const response = await fetchHelloAda(`/api/helloada/messages?${query}`, { cache: 'no-store' })
      const body = await response.json() as ResponseData & { message?: string }
      if (response.status === 401) setSessionAvailable(false)
      if (!response.ok) throw new Error(body.message || t('owner.messagesFailure'))
      setSessionAvailable(true)
      setMailbox(body.mailbox)
      if (tab === 'contacts') setContacts(body.contacts || [])
      else {
        const rows = body.conversations || []
        setConversations(rows)
        setActiveId((current) => current && rows.some((item) => String(item.id) === current)
          ? current
          : rows.some((item) => String(item.id) === deepLinkConversation)
            ? deepLinkConversation
            : String(rows[0]?.id || ''))
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('owner.messagesFailure'))
    } finally { if (!quiet) setLoading(false) }
  }, [deepLinkConversation, filter, search, t, tab])

  useEffect(() => { void load() }, [load])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const conversationId = params.get('conversation') || ''
    if (!conversationId) return
    setDeepLinkConversation(conversationId)
    setFilter('all')
  }, [])

  useEffect(() => {
    if (notificationAddressTouched.current || !mailbox) return
    setNotificationAddress(mailbox.notificationPendingAddress || mailbox.notificationAddress || '')
  }, [mailbox?.notificationAddress, mailbox?.notificationPendingAddress])

  useEffect(() => {
    if (tab !== 'inbox' || !activeId) { setDetail(undefined); return }
    const controller = new AbortController()
    void fetchHelloAda(`/api/helloada/messages/${encodeURIComponent(activeId)}`, { cache: 'no-store', signal: controller.signal })
      .then(async (response) => {
        const body = await response.json() as ResponseData & { message?: string }
        if (!response.ok) throw new Error(body.message || t('owner.messagesFailure'))
        setDetail(body)
        const latestDraft = [...(body.messages || [])].reverse().find((item) => item.direction === 'reply' && item.deliveryState === 'draft' && item.draftText)
        setDraft(latestDraft?.draftText || '')
        setDraftRevision(Number(latestDraft?.draftRevision || 0))
        draftDirtyRef.current = false
        setDraftHash('')
        setError('')
      })
      .catch((cause) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : t('owner.messagesFailure')) })
    return () => controller.abort()
  }, [activeId, tab, t])

  useEffect(() => {
    if (tab !== 'inbox' || !sessionAvailable) return
    let controller: AbortController | undefined
    const refresh = () => {
      if (document.visibilityState !== 'visible') return
      void load(true)
      if (!activeId || draftDirtyRef.current) return
      controller?.abort()
      controller = new AbortController()
      const signal = controller.signal
      void fetchHelloAda(`/api/helloada/messages/${encodeURIComponent(activeId)}`, { cache: 'no-store', signal })
        .then(async (response) => {
          if (response.status === 401) { setSessionAvailable(false); return }
          if (!response.ok) return
          const next = await response.json() as ResponseData
          setDetail(next)
          const latestDraft = [...(next.messages || [])].reverse().find((item) => item.direction === 'reply' && item.deliveryState === 'draft' && item.draftText)
          if (latestDraft) {
            setDraft(latestDraft.draftText || '')
            setDraftRevision(Number(latestDraft.draftRevision || 0))
          } else {
            setDraft('')
            setDraftRevision(0)
          }
        })
        .catch(() => undefined)
    }
    const timer = window.setInterval(refresh, 30_000)
    return () => { window.clearInterval(timer); controller?.abort() }
  }, [activeId, load, sessionAvailable, tab])

  const saveDraft = async () => {
    if (!activeId || !draft.trim() || saving) return
    setSaving(true); setError(''); setNotice('')
    try {
      const response = await fetchHelloAda(`/api/helloada/messages/${encodeURIComponent(activeId)}/draft`, {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ replyText: draft, expectedRevision: draftRevision }),
      })
      const body = await response.json() as { draftHash?: string; draftRevision?: number; message?: string }
      if (!response.ok || !body.draftHash || !Number.isInteger(body.draftRevision)) throw new Error(body.message || t('owner.messagesFailure'))
      setDraftHash(body.draftHash)
      setDraftRevision(body.draftRevision!)
      draftDirtyRef.current = false
      setNotice(t('owner.messagesDraftSaved'))
      await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('owner.messagesFailure')) }
    finally { setSaving(false) }
  }

  const draftWithAda = async () => {
    if (!activeId || draftingWithAda) return
    setDraftingWithAda(true); setError(''); setNotice('')
    try {
      const response = await fetchHelloAda(`/api/helloada/messages/${encodeURIComponent(activeId)}/draft-with-ada`, {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({}),
      })
      const body = await response.json() as { draft?: string; message?: string }
      if (!response.ok || typeof body.draft !== 'string' || !body.draft.trim()) throw new Error(body.message || t('owner.messagesAdaFailure'))
      setDraft(body.draft)
      setDraftHash('')
      sendRequestRef.current = undefined
      draftDirtyRef.current = true
      setNotice(t('owner.messagesAdaDraftReady'))
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('owner.messagesAdaFailure')) }
    finally { setDraftingWithAda(false) }
  }

  const sendReply = async () => {
    if (!activeId || !draftHash || sending) return
    setSending(true); setError(''); setNotice('')
    try {
      const response = await fetchHelloAda(`/api/helloada/messages/${encodeURIComponent(activeId)}/send`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ draftHash, requestId: sendRequestRef.current?.draftHash === draftHash ? sendRequestRef.current.requestId : (sendRequestRef.current = { draftHash, requestId: globalThis.crypto.randomUUID() }).requestId }),
      })
      const body = await response.json() as { message?: string }
      if (!response.ok) throw new Error(body.message || t('owner.messagesSendFailure'))
      sendRequestRef.current = undefined
      setConfirmSend(false); setNotice(t('owner.messagesSent')); setDraft(''); setDraftHash(''); setDraftRevision(0)
      const refreshed = await fetchHelloAda(`/api/helloada/messages/${encodeURIComponent(activeId)}`, { cache: 'no-store' })
      if (refreshed.ok) setDetail(await refreshed.json() as ResponseData)
      await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('owner.messagesSendFailure')) }
    finally { setSending(false) }
  }

  const updateState = async (state: Conversation['state']) => {
    if (!activeId) return
    setError('')
    try {
      const response = await fetchHelloAda(`/api/helloada/messages/${encodeURIComponent(activeId)}/state`, {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ state }),
      })
      const body = await response.json() as { message?: string }
      if (!response.ok) throw new Error(body.message || t('owner.messagesFailure'))
      await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('owner.messagesFailure')) }
  }

  const updateNotificationMailbox = (value: unknown) => {
    const next = value && typeof value === 'object' ? value as Partial<Mailbox> : {}
    setMailbox((current) => current ? { ...current, ...next } : { state: 'active', ...next })
  }

  const requestNotificationCode = async () => {
    if (!notificationAddress.trim() || savingNotification) return
    setSavingNotification(true); setError(''); setNotice('')
    try {
      const response = await fetchHelloAda('/api/helloada/messages/notifications/start', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ address: notificationAddress.trim() }),
      })
      const body = await response.json() as { state?: string; mailbox?: Partial<Mailbox>; message?: string }
      updateNotificationMailbox(body.mailbox)
      if (!response.ok) throw new Error(body.message || t('owner.messagesNotificationFailure'))
      if (body.state === 'verification_sent') setNotice(t('owner.messagesNotificationCodeSent'))
      else setNotice(t('owner.messagesNotificationVerified'))
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('owner.messagesNotificationFailure')) }
    finally { setSavingNotification(false) }
  }

  const verifyNotificationCode = async () => {
    if (!/^\d{8}$/.test(notificationCode) || savingNotification) return
    setSavingNotification(true); setError(''); setNotice('')
    try {
      const response = await fetchHelloAda('/api/helloada/messages/notifications/verify', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ code: notificationCode }),
      })
      const body = await response.json() as { mailbox?: Partial<Mailbox>; message?: string }
      if (!response.ok) throw new Error(body.message || t('owner.messagesNotificationFailure'))
      updateNotificationMailbox(body.mailbox)
      notificationAddressTouched.current = false
      setNotificationAddress(String(body.mailbox?.notificationAddress || notificationAddress.trim()))
      setNotificationCode('')
      setNotice(t('owner.messagesNotificationVerified'))
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('owner.messagesNotificationFailure')) }
    finally { setSavingNotification(false) }
  }

  const disableNotifications = async () => {
    if (savingNotification) return
    setSavingNotification(true); setError(''); setNotice('')
    try {
      const response = await fetchHelloAda('/api/helloada/messages/notifications/disable', { method: 'POST' })
      const body = await response.json() as { mailbox?: Partial<Mailbox>; message?: string }
      if (!response.ok) throw new Error(body.message || t('owner.messagesNotificationFailure'))
      updateNotificationMailbox(body.mailbox)
      notificationAddressTouched.current = false
      setNotificationAddress(''); setNotificationCode('')
      setNotice(t('owner.messagesNotificationDisabled'))
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('owner.messagesNotificationFailure')) }
    finally { setSavingNotification(false) }
  }

  const activeContact = detail?.conversation ? contactOf(detail.conversation.contact) : undefined
  const canSend = mailbox?.state === 'active' && Boolean(mailbox.address)

  return <main className="helloada-messages" aria-label={t('owner.messages')}>
    <header className="helloada-messages-header">
      <div><span className="helloada-eyebrow">{t('owner.messages')}</span><h1>{t('owner.messagesTitle')}</h1><p>{t('owner.messagesIntro')}</p></div>
      <Link className="helloada-messages-manage-form" href="/admin/collections/contactForms">{t('owner.messagesForms')}<WorkspaceIcon name="arrow" size={16} /></Link>
    </header>
    <div className={`helloada-mailbox-status ${canSend ? 'is-active' : 'is-pending'}`} role="status">
      <span className="helloada-mailbox-indicator" />
      <span>{canSend ? t('owner.messagesMailboxActive') : t('owner.messagesMailboxSetup')}</span>
      {canSend ? <strong>{mailbox?.address}</strong> : null}
    </div>
    <section className="helloada-message-notifications" aria-labelledby="helloada-notification-title">
      <div className="helloada-message-notifications-copy">
        <h2 id="helloada-notification-title">{t('owner.messagesNotificationTitle')}</h2>
        <p>{t('owner.messagesNotificationIntro')}</p>
        {mailbox?.notificationVerifiedAt && mailbox.notificationAddress
          ? <small>{t('owner.messagesNotificationActive')} <strong>{mailbox.notificationAddress}</strong></small>
          : <small>{t('owner.messagesNotificationOff')}</small>}
        {mailbox?.notificationPendingAddress ? <small>{t('owner.messagesNotificationPending')} <strong>{mailbox.notificationPendingAddress}</strong></small> : null}
      </div>
      <div className="helloada-message-notification-controls">
        <label>
          <span>{t('owner.messagesNotificationAddress')}</span>
          <input type="email" autoComplete="email" maxLength={254} value={notificationAddress} onChange={(event) => { notificationAddressTouched.current = true; setNotificationAddress(event.target.value) }} placeholder={t('owner.messagesNotificationPlaceholder')} />
        </label>
        <button type="button" onClick={() => void requestNotificationCode()} disabled={!notificationAddress.trim() || savingNotification || !canSend}>{savingNotification ? t('owner.messagesLoading') : t('owner.messagesNotificationSendCode')}</button>
        {mailbox?.notificationPendingAddress ? <>
          <label>
            <span>{t('owner.messagesNotificationCode')}</span>
            <input type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={8} pattern="[0-9]{8}" value={notificationCode} onChange={(event) => setNotificationCode(event.target.value.replace(/\D/g, '').slice(0, 8))} placeholder="00000000" />
          </label>
          <button type="button" onClick={() => void verifyNotificationCode()} disabled={!/^\d{8}$/.test(notificationCode) || savingNotification}>{t('owner.messagesNotificationVerify')}</button>
        </> : null}
        {mailbox?.notificationVerifiedAt ? <button type="button" className="is-secondary" onClick={() => void disableNotifications()} disabled={savingNotification}>{t('owner.messagesNotificationDisable')}</button> : null}
      </div>
    </section>
    <div className="helloada-messages-toolbar">
      <div className="helloada-messages-tabs" role="tablist" aria-label={t('owner.messages')}>
        <button type="button" role="tab" aria-selected={tab === 'inbox'} className={tab === 'inbox' ? 'is-active' : ''} onClick={() => setTab('inbox')}>{t('owner.messagesInbox')}</button>
        <button type="button" role="tab" aria-selected={tab === 'contacts'} className={tab === 'contacts' ? 'is-active' : ''} onClick={() => setTab('contacts')}>{t('owner.messagesContacts')}</button>
      </div>
      {tab === 'inbox' ? <label className="helloada-messages-filter"><span className="sr-only">{t('owner.messagesStatus')}</span><select value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)}>
        <option value="needs_reply">{t('owner.messagesFilterNeedsReply')}</option><option value="all">{t('owner.messagesFilterAll')}</option><option value="done">{t('owner.messagesFilterDone')}</option><option value="archived">{t('owner.messagesFilterArchived')}</option><option value="spam">{t('owner.messagesFilterSpam')}</option>
      </select></label> : null}
      <input className="helloada-messages-search" type="search" value={search} placeholder={t('owner.messagesSearch')} onChange={(event) => setSearch(event.target.value)} />
      <button type="button" className="helloada-messages-refresh" onClick={() => void load()} disabled={loading} aria-label={t('owner.retry')}><WorkspaceIcon name="refresh" size={17} /></button>
    </div>
    {error ? <p className="helloada-messages-error" role="alert">{error}</p> : null}
    {notice ? <p className="helloada-messages-notice" role="status">{notice}</p> : null}

    {tab === 'inbox' ? <div className="helloada-messages-layout">
      <aside className="helloada-messages-list" aria-label={t('owner.messagesInbox')}>
        {loading ? <p className="helloada-messages-empty">{t('owner.messagesLoading')}</p> : conversations.length ? conversations.map((conversation) => {
          const person = contactOf(conversation.contact)
          const selected = String(conversation.id) === activeId
          return <button type="button" key={conversation.id} className={`helloada-conversation-row${selected ? ' is-active' : ''}${conversation.unread ? ' is-unread' : ''}`} onClick={() => setActiveId(String(conversation.id))}>
            <span className="helloada-conversation-avatar">{(person?.name || person?.email || conversation.participantEmail || '•').slice(0, 1).toUpperCase()}</span>
            <span className="helloada-conversation-copy"><strong>{person?.name || person?.email || conversation.participantEmail || t('owner.messagesNoSubject')}</strong><span>{conversation.subject || t('owner.messagesNoSubject')}</span><small>{conversation.lastMessagePreview || (conversation.source === 'form' ? t('owner.messagesFromForm') : t('owner.messagesFromEmail'))}</small></span>
            <time>{conversation.lastActivityAt ? new Date(conversation.lastActivityAt).toLocaleDateString() : ''}</time>
          </button>
        }) : <p className="helloada-messages-empty">{t('owner.messagesEmpty')}</p>}
      </aside>
      <section className="helloada-message-detail" aria-label={t('owner.messages')}>
        {detail?.conversation ? <>
          <header className="helloada-message-detail-header">
            <div><span className="helloada-eyebrow">{detail.conversation.source === 'form' ? t('owner.messagesFromForm') : t('owner.messagesFromEmail')}</span><h2>{detail.conversation.subject || t('owner.messagesNoSubject')}</h2><p>{activeContact?.name ? `${activeContact.name} · ` : ''}{activeContact?.email || detail.conversation.participantEmail}</p></div>
            {detail.conversation.state !== 'done' ? <button type="button" onClick={() => void updateState('done')}>{t('owner.messagesMarkDone')}</button> : <button type="button" onClick={() => void updateState('needs_reply')}>{t('owner.messagesNeedsReply')}</button>}
          </header>
          <div className="helloada-message-thread">
            {(detail.messages || []).map((message) => <article key={message.id} className={`helloada-message-bubble is-${message.direction}`}>
              <div><strong>{message.direction === 'reply' ? t('owner.messagesFrom') : message.from}</strong><time>{message.createdAt ? new Date(message.createdAt).toLocaleString() : ''}</time></div>
              <p>{message.text}</p>
              {message.attachmentManifest?.filter((attachment) => attachment.allowed).map((attachment) => <a className="helloada-message-attachment" key={attachment.index} href={`/api/helloada/messages/${encodeURIComponent(String(message.id))}/attachments/${attachment.index}`}><WorkspaceIcon name="arrow" size={14} />{attachment.filename || t('owner.messagesDownloadAttachment')}</a>)}
              {message.deliveryState && message.deliveryState !== 'received' ? <small>{message.deliveryState}</small> : null}
            </article>)}
          </div>
          <div className="helloada-message-reply">
            <label htmlFor="helloada-reply">{t('owner.messagesReply')}</label>
            <button type="button" className="helloada-message-ada-draft" onClick={() => void draftWithAda()} disabled={draftingWithAda}>{draftingWithAda ? t('owner.messagesDrafting') : t('owner.messagesAskAda')}</button>
            <textarea id="helloada-reply" value={draft} onChange={(event) => { draftDirtyRef.current = true; setDraft(event.target.value); setDraftHash(''); sendRequestRef.current = undefined }} placeholder={t('owner.messagesDraftPlaceholder')} rows={5} maxLength={10000} />
            <div className="helloada-message-reply-actions">
              <button type="button" className="is-secondary" onClick={() => void saveDraft()} disabled={!draft.trim() || saving}>{saving ? t('owner.messagesLoading') : t('owner.messagesSaveDraft')}</button>
              <button type="button" onClick={() => setConfirmSend(true)} disabled={!draftHash || !canSend || sending}>{t('owner.messagesSend')}</button>
            </div>
            {!canSend ? <small>{t('owner.messagesNoMailbox')}</small> : null}
          </div>
        </> : <div className="helloada-messages-empty helloada-message-placeholder">{loading ? t('owner.messagesLoading') : t('owner.messagesSelect')}</div>}
      </section>
    </div> : <div className="helloada-contacts-layout">
      <section className="helloada-contact-list" aria-label={t('owner.messagesContacts')}>
        {loading ? <p className="helloada-messages-empty">{t('owner.messagesLoading')}</p> : contacts.length ? contacts.map((contact) => <button type="button" key={contact.id} className={String(contact.id) === activeContactId ? 'is-active' : ''} onClick={() => setActiveContactId(String(contact.id))}>
          <span className="helloada-conversation-avatar">{(contact.name || contact.email || '•').slice(0, 1).toUpperCase()}</span><span><strong>{contact.name || contact.email}</strong><small>{contact.email}{contact.company ? ` · ${contact.company}` : ''}</small></span>
        </button>) : <p className="helloada-messages-empty">{t('owner.messagesNoContacts')}</p>}
      </section>
      <section className="helloada-contact-detail">
        {contacts.find((item) => String(item.id) === activeContactId) ? (() => {
          const contact = contacts.find((item) => String(item.id) === activeContactId)!
          return <><span className="helloada-eyebrow">{t('owner.messagesContacts')}</span><h2>{contact.name || contact.email}</h2><p>{contact.email}</p>{contact.phone ? <p>{contact.phone}</p> : null}{contact.company ? <p>{contact.company}</p> : null}{contact.notes ? <blockquote>{contact.notes}</blockquote> : null}</>
        })() : <p className="helloada-messages-empty">{t('owner.messagesNoContacts')}</p>}
      </section>
    </div>}

    {confirmSend ? <div className="helloada-send-confirm-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setConfirmSend(false) }}>
      <section className="helloada-send-confirm" role="dialog" aria-modal="true" aria-labelledby="helloada-send-title">
        <span className="helloada-eyebrow">{t('owner.messagesReply')}</span><h2 id="helloada-send-title">{t('owner.messagesSendConfirm')}</h2><p>{t('owner.messagesSendConfirmBody')}</p>
        <dl><div><dt>{t('owner.messagesFrom')}</dt><dd>{mailbox?.address}</dd></div><div><dt>{t('owner.messagesTo')}</dt><dd>{activeContact?.email || detail?.conversation?.participantEmail}</dd></div><div><dt>{t('owner.messagesSubject')}</dt><dd>{detail?.conversation?.subject || t('owner.messagesNoSubject')}</dd></div></dl>
        <div><button type="button" className="is-secondary" onClick={() => setConfirmSend(false)}>{t('owner.messagesCancel')}</button><button type="button" onClick={() => void sendReply()} disabled={sending}>{sending ? t('owner.messagesLoading') : t('owner.messagesSend')}</button></div>
      </section>
    </div> : null}
  </main>
}
