import { publicRevisionAttributes } from '@/lib/public-revision'

type DocumentRevision = Record<string, unknown>

/** Proof of the actual Payload input supplied to a public presentation. */
export function PublicRevision({ document }: { document: DocumentRevision }) {
  // A hidden sibling has no layout effect and does not wrap the designed DOM.
  return <span hidden {...publicRevisionAttributes(document)} />
}

export function PublicRevisionList({ documents }: { documents: DocumentRevision[] }) {
  return <>{documents.map(document => <PublicRevision key={String(document.id)} document={document} />)}</>
}
