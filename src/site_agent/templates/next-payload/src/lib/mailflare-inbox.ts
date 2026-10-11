import type { MailflareD1 } from '../../mailflare-provisioning'

type FormSubmission = {
  answers: Record<string, string | boolean>
  contact: { name?: string; email: string; phone?: string; company?: string }
  message: string
}
type FormField = { key: string; label?: string; mapsTo?: string; type?: string }
type ExistingMessage = { id: string; from_addr: string; to_addr: string; subject: string | null; text_body: string | null }

const digest = async (value: string) => {
  const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))
  return [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}
const cleanText = (value: string) => value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '').trim()

const cleanHeader = (value: string) => cleanText(value).replaceAll('\n', ' ').replaceAll('\r', ' ').replaceAll('\t', ' ').replace(/\s+/g, ' ').trim()
export async function writeMailflareFormMessage({
  database, tenantId, mailboxAddress, formSlug, formTitle, requestId, sourcePage, fields, submission,
}: {
  database: MailflareD1
  tenantId: string
  mailboxAddress: string
  formSlug: string
  formTitle: string
  requestId: string
  sourcePage: string
  fields: FormField[]
  submission: FormSubmission
}): Promise<{ messageId: string; duplicate: boolean }> {
  const address = mailboxAddress.trim().toLowerCase()
  const normalizedEmail = submission.contact.email.trim().toLowerCase()
  const mailbox = await database.prepare(
    `SELECT m.id, m.user_id, m.disabled, d.status, m.local_part, d.hostname
     FROM mailboxes m INNER JOIN domains d ON d.id = m.domain_id
     WHERE lower(m.local_part || '@' || d.hostname) = ? LIMIT 1`,
  ).bind(address).first<{ id: string; user_id: string; disabled: number; status: string; local_part: string; hostname: string }>()
  if (!mailbox || mailbox.disabled || mailbox.status !== 'active' || !mailbox.user_id) {
    throw new Error('The tenant Mailflare mailbox is not active')
  }

  const messageId = `webform_${(await digest(`${tenantId}:${formSlug}:${requestId}`)).slice(0, 32)}`
  const name = cleanHeader(submission.contact.name || '').slice(0, 160)
  const fromAddress = name ? `"${name.replace(/[\\"]/g, '')}" <${normalizedEmail}>` : normalizedEmail
  const title = cleanHeader(formTitle).slice(0, 160) || formSlug
  const subject = `Website enquiry — ${title}`.slice(0, 180)
  const extraAnswers = fields.flatMap((field) => {
    if (field.type === 'consent' || field.mapsTo !== 'none') return []
    const value = submission.answers[field.key]
    return typeof value === 'string' && value ? [`${cleanText(field.label || field.key)}: ${cleanText(value)}`] : []
  })
  const textBody = [
    name && `Name: ${name}`,
    submission.contact.company && `Company: ${cleanText(submission.contact.company)}`,
    submission.contact.phone && `Phone: ${cleanText(submission.contact.phone)}`,
    `Email: ${normalizedEmail}`,
    sourcePage && `Page: ${cleanText(sourcePage)}`,
    '',
    cleanText(submission.message),
    extraAnswers.length ? `\nAdditional details\n${extraAnswers.join('\n')}` : '',
  ].filter((line) => line !== undefined && line !== null).join('\n').trim()

  const existing = await database.prepare(
    'SELECT id, from_addr, to_addr, subject, text_body FROM messages WHERE id = ? LIMIT 1',
  ).bind(messageId).first<ExistingMessage>()
  if (existing) {
    if (existing.from_addr !== fromAddress || existing.to_addr !== address || existing.subject !== subject || existing.text_body !== textBody) {
      throw new Error('This form request ID was already used for different answers')
    }
    return { messageId, duplicate: true }
  }

  const now = Date.now()
  const contactId = `${mailbox.user_id}:${normalizedEmail}`
  await database.prepare(
    `INSERT INTO contacts (id, user_id, email, display_name, source, last_seen_at, created_at)
     VALUES (?, ?, ?, ?, 'inbound', ?, ?)
     ON CONFLICT(user_id, email) DO UPDATE SET
       display_name = CASE WHEN contacts.source = 'manual' OR contacts.display_name IS NOT NULL
         THEN contacts.display_name ELSE excluded.display_name END,
       source = CASE WHEN contacts.source IN ('manual', 'outbound') THEN contacts.source ELSE 'inbound' END,
       last_seen_at = excluded.last_seen_at`,
  ).bind(contactId, mailbox.user_id, normalizedEmail, name || null, now, now).run()
  await database.prepare(
    `INSERT OR IGNORE INTO messages
       (id, user_id, mailbox_id, direction, provider_message_id, from_addr, to_addr, subject, snippet, text_body, status, thread_id, created_at)
     VALUES (?, ?, ?, 'inbound', ?, ?, ?, ?, ?, ?, 'received', ?, ?)`,
  ).bind(
    messageId, mailbox.user_id, mailbox.id,
    `helloada-form:${tenantId}:${formSlug}:${requestId}`,
    fromAddress, address, subject, cleanText(submission.message).slice(0, 240),
    textBody, messageId, now,
  ).run()

  const accepted = await database.prepare(
    'SELECT id, from_addr, to_addr, subject, text_body FROM messages WHERE id = ? LIMIT 1',
  ).bind(messageId).first<ExistingMessage>()
  if (!accepted || accepted.from_addr !== fromAddress || accepted.to_addr !== address || accepted.subject !== subject || accepted.text_body !== textBody) {
    throw new Error('Mailflare did not confirm the website form message')
  }
  return { messageId, duplicate: false }
}
