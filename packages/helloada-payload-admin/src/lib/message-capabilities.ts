export type BusinessMailbox = {
  address?: string
  state?: string
  outboundProvider?: string
  outboundMode?: string
}

export const isBusinessCorrespondenceReady = (mailbox?: BusinessMailbox): boolean =>
  mailbox?.state === 'active'
  && Boolean(mailbox.address?.trim())
  && mailbox.outboundProvider === 'resend'
  && mailbox.outboundMode === 'business_correspondence'
