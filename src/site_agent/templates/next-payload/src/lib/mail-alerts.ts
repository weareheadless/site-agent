export type MailArrivalReport = {
  messageId: string
  subject?: string
  from?: string
  kind?: 'inbound' | 'enquiry'
}

/**
 * The bindings one tenant needs to report a mail arrival.
 *
 * The report is read from the Worker environment that the handler already
 * holds. The Cloudflare request context is not available in the Worker's own
 * email and queue handlers, and a missing binding is never a reason to fail
 * mail delivery.
 */
export type MailAlertEnv = {
  SITE_AGENT_URL?: string
  HELLOADA_SITE_AGENT_TOKEN?: string
}

/**
 * Report one mail arrival to the platform.
 *
 * The tenant Worker owns the mailbox and the platform owns the owner's alert
 * settings, so the Worker reports the arrival and the platform decides
 * whether anybody is warned and how. A failed report never blocks mail: the
 * message is already stored, and the report is only a notice.
 */
export async function reportMailArrival(env: MailAlertEnv, report: MailArrivalReport): Promise<void> {
  const url = String(env?.SITE_AGENT_URL || '').replace(/\/$/, '')
  const token = String(env?.HELLOADA_SITE_AGENT_TOKEN || '')
  const messageId = String(report.messageId || '').trim()
  if (!url || !token || !messageId) return
  try {
    const response = await fetch(`${url}/workspace/mail/notification`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        messageId,
        subject: String(report.subject || ''),
        from: String(report.from || ''),
        kind: report.kind || 'inbound',
      }),
    })
    if (!response.ok) {
      console.error('helloada_mail_arrival_report_rejected', { status: response.status })
    }
  } catch (error) {
    console.error('helloada_mail_arrival_report_failed', {
      error: error instanceof Error ? error.message : 'unknown',
    })
  }
}

/** Read the identity and subject of one inbound message without consuming it. */
export function describeInboundMessage(message: unknown): { messageId: string; subject: string; from: string } {
  const headers = (message as { headers?: { get?: (name: string) => string | null } } | null)?.headers
  const read = (name: string) => {
    try {
      return String(headers?.get?.(name) || '').trim()
    } catch {
      return ''
    }
  }
  const from = String((message as { from?: unknown } | null)?.from || '').trim()
  const subject = read('subject')
  const identifier = read('message-id') || read('Message-ID')
  const messageId = identifier || `${from}|${subject}|${read('date')}`
  return { messageId: messageId.slice(0, 200), subject: subject.slice(0, 200), from: from.slice(0, 200) }
}
