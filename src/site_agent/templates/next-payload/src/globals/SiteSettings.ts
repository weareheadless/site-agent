import type { GlobalConfig } from 'payload'

export const SiteSettings: GlobalConfig = {
  slug: 'siteSettings',
  fields: [
    { name: 'siteName', type: 'text', required: true, defaultValue: 'Your website' },
    { name: 'description', type: 'textarea' },
  ],
}
