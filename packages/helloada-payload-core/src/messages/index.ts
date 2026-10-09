export type HelloAdaFormField = {
  key: string
  label: string
  type: 'text' | 'email' | 'phone' | 'textarea' | 'select' | 'consent'
  mapsTo: 'none' | 'name' | 'email' | 'phone' | 'company' | 'message'
  required?: boolean
  maxLength?: number
  choices?: Array<{ key: string; label: string }>
}

export type HelloAdaForm = {
  _status?: string
  enabled?: boolean
  fields?: HelloAdaFormField[]
}

export type HelloAdaFormSubmission = {
  answers: Record<string, string | boolean>
  contact: { name?: string; email: string; phone?: string; company?: string }
  message: string
}

const objectValue = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}

/** Trim surrounding whitespace and lowercase only the domain; never strip plus-tags or dots. */
export const normalizeHelloAdaEmail = (value: unknown): string => {
  const address = String(value ?? '').trim()
  if (address.length > 254 || /[\r\n\0\s]/.test(address)) throw new Error('Enter a valid email address.')
  const separator = address.lastIndexOf('@')
  if (separator < 1 || separator !== address.indexOf('@')) throw new Error('Enter a valid email address.')
  const local = address.slice(0, separator)
  const domain = address.slice(separator + 1)
  if (local.length > 64 || !domain || domain.length > 253 || domain.startsWith('.') || domain.endsWith('.')) {
    throw new Error('Enter a valid email address.')
  }
  const labels = domain.split('.')
  if (labels.length < 2 || labels.some((label) => !/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/.test(label))) {
    throw new Error('Enter a valid email address.')
  }
  if (!/^[^<>(),;:\\"\[\]]+$/.test(local)) throw new Error('Enter a valid email address.')
  return `${local}@${domain.toLowerCase()}`
}

const answerText = (value: unknown, label: string, limit: number) => {
  if (typeof value !== 'string') throw new Error(`Enter an answer for “${label}”.`)
  const answer = value.trim()
  if (answer.length > limit) throw new Error(`The answer for “${label}” is too long.`)
  return answer
}

/** Validate a public submission against the exact enabled, published Payload form. */
export const validateHelloAdaFormSubmission = (
  formValue: HelloAdaForm,
  input: unknown,
): HelloAdaFormSubmission => {
  const form = objectValue(formValue)
  if (form._status !== 'published' || form.enabled !== true) throw new Error('This form is not accepting messages.')
  if (!Array.isArray(form.fields) || form.fields.length < 1 || form.fields.length > 12) throw new Error('This form is not configured correctly.')
  const body = objectValue(input)
  const submitted = objectValue(body.answers)
  if (new TextEncoder().encode(JSON.stringify(body)).byteLength > 16_384) throw new Error('This form submission is too large.')
  const knownKeys = new Set(form.fields.map((field) => String(objectValue(field).key || '')))
  if (Object.keys(submitted).some((key) => !knownKeys.has(key))) throw new Error('This form submission contains an unknown field.')

  const answers: Record<string, string | boolean> = {}
  const mapped: Record<string, string> = {}
  for (const rawField of form.fields) {
    const field = objectValue(rawField)
    const key = String(field.key || '')
    const label = String(field.label || 'Answer')
    const type = String(field.type || '')
    const mapping = String(field.mapsTo || 'none')
    const raw = submitted[key]
    if (type === 'consent') {
      if (field.required === true && raw !== true) throw new Error(`Please confirm “${label}”.`)
      answers[key] = raw === true
      continue
    }
    const value = answerText(raw ?? '', label, Number(field.maxLength) || (type === 'textarea' ? 4000 : 500))
    if (field.required === true && !value) throw new Error(`Complete “${label}”.`)
    if (type === 'select' && value) {
      const choices = Array.isArray(field.choices) ? field.choices.map(objectValue) : []
      if (!choices.some((choice) => choice.key === value)) throw new Error(`Choose one of the available answers for “${label}”.`)
    }
    const checked = type === 'email' && value ? normalizeHelloAdaEmail(value) : value
    answers[key] = checked
    if (mapping !== 'none' && checked) mapped[mapping] = checked
  }

  if (!mapped.email || !mapped.message) throw new Error('This form must collect an email address and a message.')
  const contact = {
    ...(mapped.name ? { name: mapped.name.slice(0, 160) } : {}),
    email: normalizeHelloAdaEmail(mapped.email),
    ...(mapped.phone ? { phone: mapped.phone.slice(0, 80) } : {}),
    ...(mapped.company ? { company: mapped.company.slice(0, 160) } : {}),
  }
  return { answers, contact, message: mapped.message.slice(0, 4000) }
}

export const validateHelloAdaReplyText = (value: unknown): string => {
  if (typeof value !== 'string') throw new Error('Write a reply before sending.')
  const reply = value.trim()
  if (!reply || reply.length > 10_000 || /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/.test(reply)) {
    throw new Error('The reply must be plain text and no longer than 10,000 characters.')
  }
  return reply
}

export type HelloAdaMessageRecipients = { to: string; cc: string[]; bcc: string[] }

/** Owner initiated messages are intentionally small, individual correspondence. */
export const validateHelloAdaRecipients = (input: unknown): HelloAdaMessageRecipients => {
  const body = objectValue(input)
  const list = (value: unknown, required: boolean) => {
    const values = value == null ? [] : Array.isArray(value) ? value : [value]
    const normalized = values.map(normalizeHelloAdaEmail)
    if (normalized.length > 4 || new Set(normalized).size !== normalized.length) throw new Error('Use up to four unique addresses in each recipient field.')
    if (required && normalized.length !== 1) throw new Error('A new message needs one To recipient.')
    return normalized
  }
  const to = list(body.to, true)
  const cc = list(body.cc, false)
  const bcc = list(body.bcc, false)
  const all = [...to, ...cc, ...bcc]
  if (new Set(all).size !== all.length || all.length > 5) throw new Error('Recipients must be unique, with up to five addresses total.')
  return { to: to[0], cc, bcc }
}

export const validateHelloAdaSubject = (value: unknown): string => {
  if (typeof value !== 'string') throw new Error('Add a subject before sending.')
  const subject = value.replace(/[\r\n\0]/g, ' ').trim()
  if (!subject || subject.length > 180 || /[\u0000-\u001F\u007F]/.test(subject)) throw new Error('The subject must be 1 to 180 characters.')
  return subject
}

export const validateHelloAdaBookingRequest = (input: unknown) => {
  const body = objectValue(input)
  const name = String(body.name ?? '').trim()
  const email = normalizeHelloAdaEmail(body.email)
  const appointmentType = String(body.appointmentType ?? '').trim()
  const startsAt = String(body.startsAt ?? '').trim()
  const timeZone = String(body.timeZone ?? '').trim()
  if (!name || name.length > 160 || /[\u0000-\u001F\u007F]/.test(name)) throw new Error('Enter a valid name.')
  if (!/^[a-z0-9][a-z0-9-]{0,79}$/.test(appointmentType)) throw new Error('Choose a valid appointment type.')
  const date = new Date(startsAt)
  if (!startsAt || Number.isNaN(date.getTime()) || date.toISOString() !== startsAt) throw new Error('Choose a valid appointment time.')
  try { new Intl.DateTimeFormat('en', { timeZone }).format(date) } catch { throw new Error('The business time zone is not valid.') }
  const rawAnswers = objectValue(body.answers)
  if (Object.keys(rawAnswers).some((key) => key !== 'notes')) throw new Error('The booking form contains an unsupported answer.')
  const notes = rawAnswers.notes == null ? '' : String(rawAnswers.notes).trim()
  if (notes.length > 2_000 || /[\0-\x08\x0B\x0C\x0E-\x1F\x7F]/.test(notes)) throw new Error('Keep booking notes under 2,000 characters.')
  if (body.consent !== true) throw new Error('Confirm that your details may be used to manage this appointment.')
  const answers = notes ? { notes } : {}
  if (new TextEncoder().encode(JSON.stringify(body)).byteLength > 8_192) throw new Error('The booking request is too large.')
  return { name, email, appointmentType, startsAt, timeZone, answers, consent: true }
}

export const helloAdaIdempotencyKey = (value: unknown): string => {
  const key = String(value ?? '').trim()
  if (!/^[A-Za-z0-9_-]{16,128}$/.test(key)) throw new Error('A valid request ID is required.')
  return key
}
