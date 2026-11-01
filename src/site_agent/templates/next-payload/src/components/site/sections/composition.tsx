import { helloAdaBindingId } from '@weareheadless/helloada-payload-core/bindings'
import { sectionComponents } from './registry'
import { sectionDirection, sectionEntriesToContent, type SectionBinding, type MediaResolver } from './adapt'

type Value = Record<string, unknown>

/** Canonical data plumbing only. Ada supplies theme and planned behavior. */
export default function Composition({ document, collection, media }: { document: Value; collection: string; media: MediaResolver }) {
  const documentId = String(document.id || '')
  if (!documentId || !Array.isArray(document.sections) || !document.sections.length) {
    throw new Error('Composed Payload page requires an exact document and sections.')
  }
  return <main data-helloada-document-id={documentId} data-helloada-updated-at={String(document.updatedAt || '')}>
    {document.sections.map((raw: unknown) => {
      if (!raw || typeof raw !== 'object') throw new Error('Invalid composed Payload section.')
      const section = raw as Value
      const sectionKey = String(section.key || '')
      const layout = String(section.layout || '')
      const Component = sectionComponents[layout]
      if (!sectionKey || !Component || !Array.isArray(section.entries)) throw new Error('Composed Payload section has no renderable identity.')
      const { content, bindings } = sectionEntriesToContent(section.entries, (value) => {
        const resolved = media(value)
        const src = resolved.src
        if (!src) throw new Error('Composed Payload image has no canonical media URL.')
        return { src, alt: resolved.alt }
      })
      const marker = (binding?: SectionBinding) => binding ? helloAdaBindingId(collection, documentId, {
        collection, documentId, sectionKey, entryKey: binding.key, field: 'entry', property: binding.property,
      }) : undefined
      return <div key={sectionKey} id={sectionKey} data-ada-section-id={sectionKey} data-ada-section-layout={layout}>
        <Component content={content} direction={sectionDirection(section)} bindings={{
          eyebrow: marker(bindings.eyebrow), headline: marker(bindings.headline), body: marker(bindings.body),
          supporting: bindings.supporting?.map(marker), action: marker(bindings.action), image: marker(bindings.image),
          additionalImages: bindings.additionalImages?.map(marker),
        }} />
      </div>
    })}
  </main>
}
