import type { CollectionConfig } from 'payload'

export const Pages: CollectionConfig = {
  slug: 'pages',
  versions: { drafts: true, maxPerDoc: 10 },
  admin: { useAsTitle: 'title' },
  fields: [
    { name: 'title', type: 'text', required: true },
    { name: 'slug', type: 'text', required: true, unique: true },
    { name: 'summary', type: 'textarea' },
    { name: 'body', type: 'richText' },
    { name: 'published', type: 'checkbox', defaultValue: false },
  ],
}
