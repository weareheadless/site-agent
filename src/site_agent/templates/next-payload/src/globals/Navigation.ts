import type { GlobalConfig } from 'payload'
import { assertNativeWriteAllowed } from '@/lib/growth-contract'

export const Navigation: GlobalConfig = {
  slug: 'navigation',
  versions: { drafts: true },
  fields: [
    {
      name: 'items',
      type: 'array',
      fields: [
        { name: 'label', type: 'text', required: true },
        { name: 'href', type: 'text', required: true },
        { name: 'external', type: 'checkbox', defaultValue: false },
        { name: 'visible', type: 'checkbox', defaultValue: true },
      ],
    },
    {
      name: 'groups',
      type: 'array',
      fields: [
        { name: 'label', type: 'text', required: true },
        {
          name: 'items',
          type: 'array',
          fields: [
            { name: 'label', type: 'text', required: true },
            { name: 'href', type: 'text', required: true },
            { name: 'external', type: 'checkbox', defaultValue: false },
          ],
        },
      ],
    },
    {
      name: 'footer',
      type: 'array',
      fields: [
        { name: 'label', type: 'text', required: true },
        { name: 'href', type: 'text', required: true },
        { name: 'external', type: 'checkbox', defaultValue: false },
        { name: 'visible', type: 'checkbox', defaultValue: true },
      ],
    },
    {
      name: 'footerGroups',
      type: 'array',
      fields: [
        { name: 'label', type: 'text', required: true },
        {
          name: 'items',
          type: 'array',
          fields: [
            { name: 'label', type: 'text', required: true },
            { name: 'href', type: 'text', required: true },
            { name: 'external', type: 'checkbox', defaultValue: false },
          ],
        },
      ],
    },
  ],
  hooks: {
    beforeOperation: [async ({ args, operation }) => {
      if (operation === 'update') await assertNativeWriteAllowed('global:navigation', 'navigation', args.req)
    }],
  },
}
