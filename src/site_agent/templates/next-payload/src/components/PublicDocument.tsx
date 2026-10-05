import PagePresentation from '@/components/site/presentation/PagePresentation'

type RecordValue = Record<string, unknown>
type Props = {
  document: RecordValue
  settings: RecordValue
  kind: 'page' | 'post' | 'product'
  collection?: 'pages' | 'posts' | 'products'
  preview?: boolean
}

export default function PublicDocument({ document, settings, kind, collection: requestedCollection, preview = false }: Props) {
  const collection = requestedCollection || (kind === 'post' ? 'posts' : kind === 'product' ? 'products' : 'pages')
  return <PagePresentation document={document} settings={settings} kind={kind} collection={collection} preview={preview} />
}
