import type { GlobalConfig } from 'payload'

export const SiteSettings: GlobalConfig = {
  slug: 'siteSettings',
  versions: { drafts: true },
  fields: [
    { name: 'siteName', type: 'text', required: true, defaultValue: 'Your website' },
    { name: 'description', type: 'textarea' },
    { name: 'tagline', type: 'text' },
    { name: 'logo', type: 'upload', relationTo: 'media' },
    { name: 'email', type: 'email' },
    { name: 'telephone', type: 'text' },
    { name: 'facebookUrl', type: 'text' },
    { name: 'instagramUrl', type: 'text' },
    { name: 'defaultSeoTitle', type: 'text' },
    { name: 'defaultSeoDescription', type: 'textarea' },
    { name: 'defaultSocialImage', type: 'upload', relationTo: 'media' },
    {
      name: 'address',
      type: 'group',
      fields: [
        { name: 'streetAddress', type: 'text' },
        { name: 'postalCode', type: 'text' },
        { name: 'addressLocality', type: 'text' },
        { name: 'addressRegion', type: 'text' },
        { name: 'addressCountry', type: 'text' },
      ],
    },
  ],
}
