import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { JWTAuthentication } from 'payload'

import {
  HELLOADA_CAPABILITIES,
  HELLOADA_AUTHORING_CAPABILITIES,
  createHelloAdaAuthoringContract,
  createHelloAdaContentContract,
  createHelloAdaSchema,
  validateHelloAdaLink,
  validateHelloAdaFormFields,
  validateHelloAdaNavigation,
  validateHelloAdaPageSections,
  validateHelloAdaAuthoringData,
} from '../src/schema/index.ts'

test('all standard tenant schemas come from one contract and share the native mutation guard', async () => {
  const guarded = []
  const schema = createHelloAdaSchema(async (...args) => guarded.push(args))
  const collections = Object.fromEntries(schema.collections.map((item) => [item.slug, item]))
  const globals = Object.fromEntries(schema.globals.map((item) => [item.slug, item]))
  assert.deepEqual(Object.keys(collections), ['users', 'owner-handoff-grants', 'pages', 'posts', 'postCategories', 'products', 'productCategories', 'media', 'contactForms', 'appointmentTypes', 'calendarEvents', 'calendarSlotLocks', 'contacts', 'conversations', 'messages', 'messageOperations'])
  assert.deepEqual(Object.keys(globals), ['siteSettings', 'navigation', 'messageMailbox', 'calendarSettings'])
  const messageOperations = collections.messageOperations.fields.find((field) => field.name === 'operationType')
  assert.deepEqual(collections.users.auth.disableLocalStrategy, { enableFields: true })
  assert.equal(collections.users.auth.useSessions, true)
  assert.equal(collections.users.auth.strategies.length, 1)
  assert.equal(collections.users.auth.strategies[0].name, 'helloada-payload-session')
  assert.equal(collections.users.auth.strategies[0].authenticate, JWTAuthentication)
  assert.equal(collections.users.access.create(), false)
  assert.equal(collections.users.access.read(), false)
  assert.equal(collections.users.fields.find((field) => field.name === 'helloadaSubject').required, false)
  assert.equal(collections.users.fields.find((field) => field.name === 'helloadaSubject').unique, true)
  assert.equal(collections.users.fields.find((field) => field.name === 'helloadaSubject').access.read(), false)
  assert.equal(collections.users.admin.hidden, true)
  assert.equal(collections['owner-handoff-grants'].access.create(), false)
  assert.equal(collections['owner-handoff-grants'].fields.find((field) => field.name === 'grantId').unique, true)
  assert.equal(collections['owner-handoff-grants'].admin.hidden, true)
  assert.ok(messageOperations.options.includes('owner_notification'))
  assert.equal(collections.messageOperations.fields.find((field) => field.name === 'requestHash').defaultValue, '')
  for (const fieldName of [
    'notificationAddress', 'notificationVerifiedAt', 'notificationPendingAddress', 'notificationCodeHash',
    'notificationCodeExpiresAt', 'notificationCodeSentAt', 'notificationCodeAttempts',
  ]) {
    const field = globals.messageMailbox.fields.find((item) => item.name === fieldName)
    assert.ok(field, `messageMailbox.${fieldName} is in the canonical schema`)
    assert.equal(field.access.update(), false, `messageMailbox.${fieldName} is service-only`)
  }
  for (const fieldName of ['notificationCodeHash', 'notificationPendingAddress', 'notificationCodeExpiresAt', 'notificationCodeSentAt', 'notificationCodeAttempts']) {
    assert.equal(globals.messageMailbox.fields.find((field) => field.name === fieldName).admin.hidden, true)
  }
  assert.ok(collections.pages.fields.some((field) => field.name === 'sections' && field.type === 'array'))
  assert.ok(collections.posts.fields.some((field) => field.name === 'featuredImage' && field.type === 'upload'))
  assert.ok(collections.posts.fields.some((field) => field.name === 'category' && field.type === 'relationship' && field.relationTo === 'postCategories'))
  assert.ok(collections.postCategories.fields.some((field) => field.name === 'sourceUrl'))
  assert.ok(collections.productCategories.fields.some((field) => field.name === 'sourceUrl'))
  assert.ok(collections.productCategories.fields.some((field) => field.name === 'sections' && field.type === 'array'))
  assert.ok(collections.products.fields.some((field) => field.name === 'currency' && field.type === 'text' && !field.localized))
  assert.ok(collections.products.fields.some((field) => field.name === 'gallery' && field.type === 'upload'))
  for (const field of ['sourceId', 'sourceUrl', 'originalUrl', 'dominantColors', 'suggestedUses', 'qualityNotes', 'ocrText', 'proposedKnowledge', 'analysis']) {
    assert.ok(collections.media.fields.some((item) => item.name === field), `media.${field} is in the canonical contract`)
  }
  assert.equal(collections.media.fields.find((item) => item.name === 'sourceId').required, true)
  assert.equal(typeof collections.media.hooks.beforeValidate[0], 'function')
  const newMedia = await collections.media.hooks.beforeValidate[0]({ data: { alt: 'An image' } })
  assert.match(newMedia.sourceId, /^media:/)
  assert.deepEqual(HELLOADA_CAPABILITIES.collections, ['pages', 'posts', 'postCategories', 'products', 'productCategories', 'media', 'contactForms', 'appointmentTypes', 'calendarEvents', 'calendarSlotLocks', 'contacts', 'conversations', 'messages', 'messageOperations'])
  assert.ok(globals.navigation.fields.some((field) => field.name === 'footerGroups'))
  assert.ok(globals.siteSettings.fields.some((field) => field.name === 'defaultSeoDescription'))
  assert.ok(globals.siteSettings.fields.some((field) => field.name === 'contactLabel'))
  assert.ok(collections.pages.fields.some((field) => field.name === 'sections' && field.fields[2].blocks.some((block) => block.slug === 'helloAdaContactForm')))
  assert.deepEqual(HELLOADA_CAPABILITIES.globals, ['siteSettings', 'navigation', 'messageMailbox', 'calendarSettings'])
  assert.equal(collections.contactForms.access.create, collections.contactForms.access.update)
  assert.equal(collections.appointmentTypes.access.read({ req: { user: { id: 'owner' } } }), true)
  assert.equal(collections.calendarEvents.access.read({ req: { user: { id: 'owner' } } }), true)
  assert.equal(collections.calendarEvents.access.create({ req: { user: { id: 'owner' } } }), false)
  assert.equal(collections.calendarSlotLocks.access.create({ req: { user: { id: 'owner' } } }), false)
  assert.equal(collections.calendarSlotLocks.admin.hidden, true)
  assert.equal(collections.contacts.access.create({ req: { user: { id: 'owner' } } }), false)
  assert.equal(collections.messages.access.create({ req: { user: { id: 'owner' } } }), false)
  assert.equal(collections.messages.access.read({ req: { user: { id: 'owner' } } }), true)
  assert.equal(collections.conversations.fields.find((field) => field.name === 'state').access.update({ req: { user: { id: 'owner' } } }), true)
  assert.equal(collections.conversations.fields.find((field) => field.name === 'subject').access.update({ req: { user: { id: 'owner' } } }), false)
  assert.equal(typeof collections.pages.hooks.beforeOperation[0], 'function')
  assert.equal(typeof collections.pages.hooks.beforeValidate[0], 'function')
  assert.equal(typeof collections.pages.hooks.afterOperation[0], 'function')
  assert.equal(typeof collections.pages.hooks.afterError[0], 'function')
  assert.equal(typeof globals.navigation.hooks.beforeOperation[0], 'function')
  assert.equal(typeof globals.navigation.hooks.afterChange[0], 'function')
  assert.equal(typeof globals.navigation.hooks.beforeValidate[0], 'function')
  const req = { context: {} }
  await collections.pages.hooks.beforeOperation[0]({
    args: { id: 'page-7', data: { title: 'Updated' }, req },
    operation: 'update',
  })
  await collections.pages.hooks.afterOperation[0]({ req, operation: 'update' })
  assert.deepEqual(guarded.slice(-2).map((args) => args.slice(0, 4)), [
    ['pages', 'page-7', req, 'update'],
    ['pages', undefined, req, 'complete'],
  ])
})

test('contact forms require stable field IDs, a required email and enquiry, and compatible mappings', () => {
  const valid = [
    { key: 'contact.name', label: 'Your name', type: 'text', mapsTo: 'name' },
    { key: 'contact.email', label: 'Email', type: 'email', mapsTo: 'email', required: true },
    { key: 'contact.message', label: 'How can we help?', type: 'textarea', mapsTo: 'message', required: true, maxLength: 4000 },
  ]
  assert.equal(validateHelloAdaFormFields(valid), true)
  assert.match(validateHelloAdaFormFields(valid.map((field) => field.key === 'contact.email' ? { ...field, required: false } : field)), /must require an email/)
  assert.match(validateHelloAdaFormFields(valid.map((field) => field.key === 'contact.message' ? { ...field, type: 'select' } : field)), /text input/)
  assert.match(validateHelloAdaFormFields(valid.map((field) => field.key === 'contact.name' ? { ...field, key: '' } : field)), /stable ID/)
})

test('contact forms require stable field IDs, a required email and enquiry, and compatible mappings', () => {
  const valid = [
    { key: 'contact.name', label: 'Your name', type: 'text', mapsTo: 'name' },
    { key: 'contact.email', label: 'Email', type: 'email', mapsTo: 'email', required: true },
    { key: 'contact.message', label: 'How can we help?', type: 'textarea', mapsTo: 'message', required: true, maxLength: 4000 },
  ]
  assert.equal(validateHelloAdaFormFields(valid), true)
  assert.match(validateHelloAdaFormFields(valid.map((field) => field.key === 'contact.email' ? { ...field, required: false } : field)), /must require an email/)
  assert.match(validateHelloAdaFormFields(valid.map((field) => field.key === 'contact.message' ? { ...field, type: 'select' } : field)), /text input/)
  assert.match(validateHelloAdaFormFields(valid.map((field) => field.key === 'contact.name' ? { ...field, key: '' } : field)), /stable ID/)
})

test('bootstrap capability manifest is generated from the exact Payload collections, globals and blocks', () => {
  const generated = createHelloAdaContentContract()
  const committed = JSON.parse(readFileSync(new URL('../../../src/site_agent/templates/next-payload/helloada-content-contract.json', import.meta.url), 'utf8'))
  assert.deepEqual(committed, generated)
})

test('Ada authoring capabilities expose website content only and derive nested fields from Payload', async () => {
  const contract = createHelloAdaAuthoringContract()
  assert.deepEqual(Object.keys(contract.collections), ['pages', 'posts', 'products'])
  assert.deepEqual(Object.keys(contract.globals), ['siteSettings', 'navigation'])
  assert.deepEqual(HELLOADA_AUTHORING_CAPABILITIES.collections, ['pages', 'posts', 'products'])
  assert.equal(contract.collections.pages.some((field) => field.name === 'published'), false)
  assert.equal(contract.collections.posts.some((field) => field.name === 'sourceId'), false)
  assert.equal(contract.collections.pages.find((field) => field.name === 'sections').fields
    .find((field) => field.name === 'entries').blocks.some((block) => block.slug === 'helloAdaHeading'), true)
  const bookingBlock = contract.collections.pages.find((field) => field.name === 'sections').fields
    .find((field) => field.name === 'entries').blocks.find((block) => block.slug === 'helloAdaBooking')
  assert.deepEqual(bookingBlock.fields.map((field) => field.name), ['key', 'label', 'bookingTypeId'])
  const schema = createHelloAdaSchema(async () => undefined)
  const posts = schema.collections.find((collection) => collection.slug === 'posts')
  assert.equal(typeof posts.hooks.beforeValidate[0], 'function')
  const createdPost = await posts.hooks.beforeValidate[0]({ data: { slug: 'a-useful-guide' } })
  const updatedPost = await posts.hooks.beforeValidate[0]({
    data: { slug: 'a-renamed-guide' }, originalDoc: { slug: 'a-useful-guide', sourceId: 'posts:a-useful-guide' },
  })
  assert.equal(createdPost.sourceId, 'posts:a-useful-guide')
  assert.equal(updatedPost.sourceId, 'posts:a-useful-guide')
  assert.throws(() => validateHelloAdaAuthoringData('collection', 'messages', { text: 'private' }), /Unsupported website collection/)
  assert.throws(() => validateHelloAdaAuthoringData('global', 'messageMailbox', { address: 'private@example.com' }), /Unsupported website global/)
})

test('Ada authoring validation rejects unknown nested fields, invalid blocks and malformed rich text', () => {
  assert.equal(validateHelloAdaAuthoringData('collection', 'pages', {
    title: 'Home',
    slug: 'home',
    sections: [{
      key: 'home.hero', label: 'Hero', entries: [{
        key: 'home.hero.title', blockType: 'helloAdaHeading', label: 'Main heading', text: 'Welcome', level: 'h2',
      }],
    }],
  }), true)
  assert.throws(() => validateHelloAdaAuthoringData('collection', 'pages', {
    sections: [{ key: 'home.hero', label: 'Hero', unexpected: true, entries: [] }],
  }), /unsupported fields: unexpected/)
  assert.throws(() => validateHelloAdaAuthoringData('collection', 'pages', {
    sections: [{ key: 'home.hero', label: 'Hero', entries: [{ key: 'x', blockType: 'code', label: 'Code' }] }],
  }), /unsupported content block/)
  assert.throws(() => validateHelloAdaAuthoringData('collection', 'pages', { published: true }), /unsupported fields: published/)
  assert.throws(() => validateHelloAdaAuthoringData('collection', 'pages', { body: { root: { type: 'root', children: [{ type: 'image', url: 'x' }] } } }), /unsupported Lexical node/)
})

test('link validation accepts explicit web destinations and rejects executable or ambiguous URLs', () => {
  assert.equal(validateHelloAdaLink('/contact'), true)
  assert.equal(validateHelloAdaLink('#hours'), true)
  assert.equal(validateHelloAdaLink('https://example.com/contact'), true)
  assert.equal(validateHelloAdaLink('mailto:hello@example.com'), true)
  assert.equal(validateHelloAdaLink('tel:+525555555555'), true)
  assert.notEqual(validateHelloAdaLink('/contact\u0000'), true)
  assert.notEqual(validateHelloAdaLink('/\\example.com'), true)
  assert.notEqual(validateHelloAdaLink('javascript:alert(1)'), true)
  assert.notEqual(validateHelloAdaLink('//example.com'), true)
  assert.notEqual(validateHelloAdaLink('example.com'), true)
})

test('page block identities are stable, globally unique and use Payload blockType slugs', () => {
  const valid = [{
    key: 'home.hero', label: 'Hero', entries: [
      { key: 'home.hero.heading', label: 'Main heading', blockType: 'helloAdaHeading', text: 'Welcome', level: 'h2' },
      { key: 'home.hero.cta', label: 'Primary action', blockType: 'helloAdaLink', text: 'Book now', href: '/contact' },
    ],
  }]
  assert.equal(validateHelloAdaPageSections(valid), true)
  assert.match(validateHelloAdaPageSections([{ ...valid[0], entries: [valid[0].entries[0], { ...valid[0].entries[1], key: 'home.hero' }] }]), /used more than once/)
  assert.match(validateHelloAdaPageSections([{ ...valid[0], entries: [{ key: 'heading', label: 'Heading', type: 'helloAdaHeading', text: 'Welcome' }] }]), /unsupported content type/)
  assert.match(validateHelloAdaPageSections([{ ...valid[0], entries: [{ key: '', label: 'Heading', blockType: 'helloAdaHeading' }] }]), /stable content ID/)
})

test('booking content uses one immutable Mailflare ID and rejects Payload-owned appointment relationships', () => {
  const bookingTypeId = 'ha_booking_0123456789abcdef0123456789abcdef'
  const sections = [{
    key: 'home.booking', label: 'Appointments', entries: [{
      key: 'home.booking.form', label: 'Book an appointment', blockType: 'helloAdaBooking', bookingTypeId,
    }],
  }]
  assert.equal(validateHelloAdaPageSections(sections), true)
  assert.match(validateHelloAdaPageSections([{
    key: 'home.booking', label: 'Appointments', entries: [{
      key: 'home.booking.form', label: 'Book an appointment', blockType: 'helloAdaBooking',
      bookingTypeId: 'massage', appointmentType: { id: 'legacy-payload-id' },
    }],
  }]), /booking type ID/)
  assert.equal(validateHelloAdaAuthoringData('collection', 'pages', {
    title: 'Home', slug: 'home', sections,
  }), true)
})

test('shared navigation IDs remain stable and cannot be reused across regions', () => {
  assert.equal(validateHelloAdaNavigation({ items: [{ key: 'primary.home' }], footer: [{ key: 'footer.contact' }] }), true)
  assert.match(validateHelloAdaNavigation({ items: [{ key: 'home' }], footer: [{ key: 'home' }] }), /used more than once/)
  assert.match(validateHelloAdaNavigation({ groups: [{ key: 'group', items: [{ label: 'Contact' }] }] }), /stable content ID/)
})
