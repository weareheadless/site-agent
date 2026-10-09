import { hashJson } from './payload-hash.ts'

export type OwnerMessageDraftHashInput = {
  messageId: string | number
  conversationId: string
  revision: number
  from: string
  to: string
  cc: string[]
  bcc: string[]
  subject: string
  text: string
}

export const hashOwnerMessageDraft = (message: OwnerMessageDraftHashInput) => hashJson({
  messageId: String(message.messageId),
  conversationId: message.conversationId,
  revision: message.revision,
  from: message.from,
  to: message.to,
  cc: message.cc,
  bcc: message.bcc,
  subject: message.subject,
  text: message.text,
})
