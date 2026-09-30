import type { CollectionConfig } from 'payload'

export const Products: CollectionConfig = {
  slug: 'products',
  versions: { drafts: true, maxPerDoc: 10 },
  admin: { useAsTitle: 'title' },
  fields: [
    { name: 'sourceId', type: 'text', admin: { position: 'sidebar' } },
    { name: 'title', type: 'text', required: true },
    { name: 'slug', type: 'text', required: true, unique: true },
    { name: 'summary', type: 'textarea' },
    { name: 'body', type: 'richText' },
    { name: 'featuredImage', type: 'upload', relationTo: 'media' },
    { name: 'price', type: 'number' },
    { name: 'published', type: 'checkbox', defaultValue: false },
  ],
}
