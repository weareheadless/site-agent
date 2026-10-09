type ResendMessage = {
  from: string
  to: string
  cc?: string[]
  bcc?: string[]
  subject: string
  text: string
  headers?: Record<string, string>
}

type ResendFailure = Error & { permanent?: boolean; uncertain?: boolean }

const deliveryFailure = (message: string, kind: 'permanent' | 'uncertain'): ResendFailure =>
  Object.assign(new Error(message), { [kind]: true })

export async function sendResendMessage(
  apiKey: string,
  tenant: string,
  operationId: string,
  message: ResendMessage,
) {
  if (!apiKey.trim()) throw deliveryFailure('The tenant Resend sender secret is unavailable.', 'permanent')
  const idempotencyKey = `helloada:${tenant}:${operationId}`
  if (!tenant || !operationId || idempotencyKey.length > 256) {
    throw deliveryFailure('The email operation identity is invalid.', 'permanent')
  }

  let response: Response
  try {
    response = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey,
      },
      body: JSON.stringify({
        from: message.from,
        to: [message.to],
        ...(message.cc?.length ? { cc: message.cc } : {}),
        ...(message.bcc?.length ? { bcc: message.bcc } : {}),
        subject: message.subject,
        text: message.text,
        ...(message.headers && Object.keys(message.headers).length ? { headers: message.headers } : {}),
      }),
    })
  } catch {
    throw deliveryFailure('Resend did not confirm whether it accepted the email.', 'uncertain')
  }

  if (!response.ok) {
    if (response.status >= 500 || response.status === 408 || response.status === 409) {
      throw deliveryFailure(`Resend returned an ambiguous response (HTTP ${response.status}).`, 'uncertain')
    }
    throw deliveryFailure(`Resend rejected the email (HTTP ${response.status}).`, 'permanent')
  }

  let payload: { id?: unknown }
  try {
    payload = await response.json() as { id?: unknown }
  } catch {
    throw deliveryFailure('Resend accepted the request but did not return a readable receipt.', 'uncertain')
  }
  const id = typeof payload.id === 'string' ? payload.id.trim() : ''
  if (!id || id.length > 998 || /[\r\n\0]/.test(id)) {
    throw deliveryFailure('Resend accepted the request but did not return a valid email ID.', 'uncertain')
  }
  return id
}
