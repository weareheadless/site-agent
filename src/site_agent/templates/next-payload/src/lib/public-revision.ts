export function publicRevisionAttributes(document: Record<string, unknown>) {
  const id = String(document.id ?? '').trim()
  const updatedAt = String(document.updatedAt ?? '').trim()
  if (!id || !updatedAt) throw new Error('Public rendering requires a canonical Payload document revision.')
  return { 'data-helloada-document-id': id, 'data-helloada-updated-at': updatedAt }
}
