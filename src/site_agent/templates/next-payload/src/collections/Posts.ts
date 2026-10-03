import type { CollectionConfig } from 'payload'
import { assertNativeWriteAllowed } from '@/lib/growth-contract'

export const Posts: CollectionConfig = {
  slug: 'posts',
  versions: { drafts: true, maxPerDoc: 10 },
  admin: { useAsTitle: 'title', defaultColumns: ['title', 'publishedAt', '_status', 'updatedAt'] },
  fields: [
    { name: 'sourceId', type: 'text', admin: { position: 'sidebar' } },
    { name: 'title', type: 'text', required: true },
    { name: 'slug', type: 'text', required: true, unique: true },
    { name: 'summary', type: 'textarea' },
    { name: 'body', type: 'richText' },
    { name: 'featuredImage', type: 'upload', relationTo: 'media' },
    { name: 'gallery', type: 'upload', hasMany: true, relationTo: 'media' },
    { name: 'author', type: 'text' },
    { name: 'publishedAt', type: 'date' },
    { name: 'modifiedAt', type: 'date' },
    { name: 'category', type: 'text' },
    { name: 'canonicalUrl', type: 'text' },
    {
      name: 'seo',
      type: 'group',
      fields: [
        { name: 'title', type: 'text' },
        { name: 'description', type: 'textarea' },
        { name: 'image', type: 'upload', relationTo: 'media' },
      ],
    },
    { name: 'published', type: 'checkbox', defaultValue: true },
  ],
  hooks: {
    beforeOperation: [async ({ args, operation }) => {
      if (operation === 'update' || operation === 'delete') {
        const operationArgs = args as unknown as { id?: unknown; req?: { context?: Record<string, unknown> } }
        await assertNativeWriteAllowed('posts', operationArgs.id, operationArgs.req)
      }
    }],
  },
}
