import type { CollectionConfig } from 'payload'

export const Media: CollectionConfig = {
  slug: 'media',
  access: {
    // Public pages need to render Payload-managed featured images without a
    // Payload session; mutations remain authenticated.
    read: () => true,
    create: ({ req }) => Boolean(req.user),
    update: ({ req }) => Boolean(req.user),
    delete: ({ req }) => Boolean(req.user),
  },
  upload: true,
  fields: [{ name: 'alt', type: 'text' }],
}
