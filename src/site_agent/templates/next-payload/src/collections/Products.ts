import type { CollectionConfig } from 'payload'
import { assertNativeWriteAllowed } from '@/lib/growth-contract'

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
  hooks: {
    beforeOperation: [async ({ args, operation }) => {
      if (operation === 'update' || operation === 'delete') {
        const operationArgs = args as unknown as { id?: unknown; req?: { context?: Record<string, unknown> } }
        await assertNativeWriteAllowed('products', operationArgs.id, operationArgs.req)
      }
    }],
  },
}
