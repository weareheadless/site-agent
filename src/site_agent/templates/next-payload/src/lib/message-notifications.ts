const cleanHeader = (value: unknown, limit = 180) =>
  String(value ?? '').split(/[\r\n\0]/, 1)[0].replace(/[\u0000-\u001f\u007f]/g, ' ').trim().slice(0, limit)

const cleanPreview = (value: unknown, limit = 1_200) =>
  String(value ?? '').replace(/\0/g, '').replace(/[\u0001-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '').trim().slice(0, limit)

export const createMessageNotificationCode = () => {
  const range = 100_000_000
  const ceiling = Math.floor(0x1_0000_0000 / range) * range
  const random = new Uint32Array(1)
  do globalThis.crypto.getRandomValues(random)
  while (random[0] >= ceiling)
  return String(random[0] % range).padStart(8, '0')
}

export const hashMessageNotificationCode = async (
  tenantToken: string,
  tenantId: string,
  address: string,
  code: string,
) => {
  if (!tenantToken || !tenantId || !address || !/^\d{8}$/.test(code)) throw new Error('Notification verification identity is incomplete.')
  const key = await globalThis.crypto.subtle.importKey(
    'raw', new TextEncoder().encode(tenantToken), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  )
  const value = `${tenantId}\0${address}\0${code}`
  const signature = new Uint8Array(await globalThis.crypto.subtle.sign('HMAC', key, new TextEncoder().encode(value)))
  return [...signature].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

export const equalMessageNotificationCodeHash = (left: string, right: string) => {
  if (!/^[a-f0-9]{64}$/.test(left) || !/^[a-f0-9]{64}$/.test(right)) return false
  let difference = 0
  for (let index = 0; index < left.length; index += 1) difference |= left.charCodeAt(index) ^ right.charCodeAt(index)
  return difference === 0
}

export const messageNotificationInboxUrl = (domainValue: unknown, conversationId: unknown) => {
  const domain = String(domainValue ?? '').trim().toLowerCase().replace(/\.$/, '')
  const id = String(conversationId ?? '')
  if (!/^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/.test(domain) || !/^[A-Za-z0-9_-]{1,120}$/.test(id)) {
    throw new Error('The tenant Messages link is not valid.')
  }
  const url = new URL('/admin', `https://${domain}`)
  url.searchParams.set('view', 'messages')
  url.searchParams.set('state', 'all')
  url.searchParams.set('conversation', id)
  return url.toString()
}

export const buildOwnerMessageNotification = (input: {
  mailboxAddress: string
  domain: string
  conversationId: string
  sender: string
  subject: string
  preview: string
  locale?: string
}) => {
  const locale = String(input.locale || 'en').toLowerCase().split('-')[0]
  const copy = locale === 'fr'
    ? { title: 'Nouveau message', from: 'De', subject: 'Objet', action: 'Ouvrir la conversation et répondre', note: 'Répondez depuis HelloAda pour garder les échanges au même endroit.' }
    : locale === 'es'
      ? { title: 'Mensaje nuevo', from: 'De', subject: 'Asunto', action: 'Abrir la conversación y responder', note: 'Responde desde HelloAda para mantener todo el intercambio en un solo lugar.' }
      : { title: 'New message', from: 'From', subject: 'Subject', action: 'Open the conversation and reply', note: 'Reply from HelloAda to keep the conversation together.' }
  const sender = cleanHeader(input.sender, 254) || 'Website visitor'
  const subject = cleanHeader(input.subject, 180) || '(no subject)'
  const preview = cleanPreview(input.preview)
  const url = messageNotificationInboxUrl(input.domain, input.conversationId)
  const text = [
    `${copy.title} for ${input.mailboxAddress}`,
    `${copy.from}: ${sender}`,
    `${copy.subject}: ${subject}`,
    '',
    preview || '(The message has no text preview.)',
    '',
    `${copy.action}: ${url}`,
    copy.note,
  ].join('\n')
  return { subject: `${copy.title}: ${subject}`.slice(0, 220), text }
}

export const buildNotificationVerificationEmail = (address: string, code: string, locale?: string) => {
  const language = String(locale || 'en').toLowerCase().split('-')[0]
  const copy = language === 'fr'
    ? { subject: 'Confirmez votre adresse de notification', body: `Votre code HelloAda est ${code}. Il expire dans 10 minutes. Si vous n’avez pas demandé ce code, ignorez cet e-mail.` }
    : language === 'es'
      ? { subject: 'Confirma tu correo de notificaciones', body: `Tu código de HelloAda es ${code}. Vence en 10 minutos. Si no solicitaste este código, ignora este correo.` }
      : { subject: 'Verify your notification email', body: `Your HelloAda verification code is ${code}. It expires in 10 minutes. If you did not request this code, you can ignore this email.` }
  return { to: address, subject: copy.subject, text: copy.body }
}
