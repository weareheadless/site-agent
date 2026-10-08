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

export const helloAdaIdempotencyKey = (value: unknown): string => {
  const key = String(value ?? '').trim()
  if (!/^[A-Za-z0-9_-]{16,128}$/.test(key)) throw new Error('A valid request ID is required.')
  return key
}
