type DocumentRevision = Record<string, unknown>

/** Proof of the actual Payload input supplied to a public presentation. */
export function PublicRevision({ document }: { document: DocumentRevision }) {
  const id = String(document.id ?? '').trim()
  const updatedAt = String(document.updatedAt ?? '').trim()
  if (!id || !updatedAt) throw new Error('Public rendering requires a canonical Payload document revision.')
  // A hidden sibling has no layout effect and does not wrap the designed DOM.
  return <span hidden data-helloada-document-id={id} data-helloada-updated-at={updatedAt} />
}

export function PublicRevisionList({ documents }: { documents: DocumentRevision[] }) {
  return <>{documents.map(document => <PublicRevision key={String(document.id)} document={document} />)}</>
}
