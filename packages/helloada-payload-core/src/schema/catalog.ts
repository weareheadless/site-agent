import type { CollectionConfig, Field } from 'payload'

type Row = Record<string, unknown>
const row = (value: unknown): Row => value && typeof value === 'object' && !Array.isArray(value) ? value as Row : {}
const present = (value: unknown) => value !== null && value !== undefined
const key = (value: unknown) => typeof value === 'string' && /^[a-z][a-z0-9_-]{0,79}$/.test(value)

/** Amounts use the currency's minor unit, not a hard-coded two-decimal rule. */
export const validateMinorAmount = (value: unknown): true | string =>
  !present(value) || (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0)
    ? true : 'Enter a non-negative safe integer in minor units.'

export const validateCatalogAttribute = (value: unknown): true | string => {
  const data = row(value)
  if (!key(data.key)) return 'Use a stable lowercase attribute key.'
  const fields: Record<string, string> = { text: 'valueText', number: 'valueNumber', boolean: 'valueBoolean' }
  const selected = fields[String(data.valueType)]
  if (!selected) return 'Choose a text, number or boolean attribute.'
  if (!present(data[selected]) || Object.values(fields).some((field) => field !== selected && present(data[field]))) {
    return 'An attribute must contain exactly one value matching its type.'
  }
  if (selected === 'valueNumber' && (typeof data[selected] !== 'number' || !Number.isFinite(data[selected]))) return 'Enter a finite attribute number.'
  if (selected === 'valueText' && (typeof data[selected] !== 'string' || !(data[selected] as string).trim())) return 'Enter non-empty attribute text.'
  if (selected === 'valueBoolean' && typeof data[selected] !== 'boolean') return 'Enter a boolean attribute value.'
  return true
}

export const validateCatalogOptions = (value: unknown): true | string => {
  if (value === undefined || value === null) return true
  if (!Array.isArray(value)) return 'Product options must be a list.'
  const seen = new Set<string>()
  for (const entry of value) {
    const option = row(entry)
    if (!key(option.key)) return 'Use a stable lowercase product option key.'
    if (seen.has(String(option.key))) return 'Product option keys must be unique.'
    seen.add(String(option.key))
    if (!Array.isArray(option.values) || !option.values.length) return 'Declare at least one value for each option.'
    const values = option.values.map((item) => row(item).key)
    if (values.some((value) => !key(value)) || new Set(values).size !== values.length) return 'Option value keys must be valid and unique.'
  }
  return true
}

export const validateVariantSelection = (declared: unknown, selection: unknown): true | string => {
  const validation = validateCatalogOptions(declared)
  if (validation !== true) return validation
  const options = Array.isArray(declared) ? declared : []
  if (!Array.isArray(selection) || !options.length || selection.length !== options.length) return 'Select exactly one declared value for every product option.'
  const chosen = new Set<string>()
  for (const entry of selection) {
    const item = row(entry)
    const option = options.map(row).find((option) => option.key === item.option)
    if (!option || chosen.has(String(item.option)) || !(option.values as unknown[]).some((value) => row(value).key === item.value)) {
      return 'Variant options must use unique, declared product values.'
    }
    chosen.add(String(item.option))
  }
  return true
}

export const validateCatalogProduct = (value: unknown): true | string => {
  const data = row(value)
  const amount = validateMinorAmount(data.priceMinor)
  if (amount !== true) return amount
  return validateCatalogOptions(data.options)
}

export const catalogProductFields = (): Field[] => [
  { name: 'priceMinor', type: 'number', min: 0, validate: validateMinorAmount, admin: { description: 'Integer minor units for the declared currency. Never infer a conversion from legacy price.' } },
  {
    name: 'options', type: 'array', maxRows: 10, fields: [
      { name: 'key', type: 'text', required: true },
      { name: 'label', type: 'text', localized: true, required: true },
      { name: 'values', type: 'array', minRows: 1, maxRows: 100, fields: [
        { name: 'key', type: 'text', required: true },
        { name: 'label', type: 'text', localized: true, required: true },
      ] },
    ],
  },
  { name: 'location', type: 'group', fields: [
    { name: 'address', type: 'text', localized: true },
    { name: 'city', type: 'text', index: true },
    { name: 'region', type: 'text', index: true },
    { name: 'neighbourhood', type: 'text', index: true },
    { name: 'postalCode', type: 'text' },
    { name: 'countryCode', type: 'text', maxLength: 2, minLength: 2 },
    { name: 'latitude', type: 'number', min: -90, max: 90 },
    { name: 'longitude', type: 'number', min: -180, max: 180 },
  ] },
]

const identityFields = (): Field[] => [
  { name: 'sourceId', type: 'text', unique: true, index: true, access: { update: () => false }, admin: { readOnly: true } },
  { name: 'product', type: 'relationship', relationTo: 'products', required: true, index: true },
]

export const createProductAttributesCollection = (hooks: CollectionConfig['hooks']): CollectionConfig => ({
  slug: 'productAttributes', admin: { useAsTitle: 'label' }, versions: { drafts: true, maxPerDoc: 10 },
  indexes: [
    { fields: ['product', 'key'], unique: true },
    { fields: ['key', 'valueNumber'] },
    { fields: ['key', 'valueText'] },
    { fields: ['key', 'valueBoolean'] },
  ],
  fields: [
    ...identityFields(),
    { name: 'key', type: 'text', required: true },
    { name: 'label', type: 'text', localized: true, required: true },
    { name: 'valueType', type: 'select', required: true, options: ['text', 'number', 'boolean'] },
    { name: 'valueText', type: 'text' },
    { name: 'valueNumber', type: 'number' },
    { name: 'valueBoolean', type: 'checkbox' },
    { name: 'unit', type: 'text' },
    { name: 'group', type: 'text' },
    { name: 'filterable', type: 'checkbox', defaultValue: false },
    { name: 'published', type: 'checkbox', defaultValue: false },
  ],
  hooks: { ...hooks, beforeValidate: [async ({ data, originalDoc }) => {
    const result = validateCatalogAttribute({ ...originalDoc, ...data })
    if (result !== true) throw new Error(result)
    return { ...data, sourceId: originalDoc?.sourceId || data?.sourceId || `attribute:${globalThis.crypto.randomUUID()}` }
  }] },
})

export const createProductVariantsCollection = (hooks: CollectionConfig['hooks']): CollectionConfig => ({
  slug: 'productVariants', admin: { useAsTitle: 'sku' }, versions: { drafts: true, maxPerDoc: 10 },
  indexes: [{ fields: ['product', 'selectionKey'], unique: true }],
  fields: [
    ...identityFields(),
    { name: 'sku', type: 'text', required: true, unique: true },
    { name: 'options', type: 'array', required: true, minRows: 1, maxRows: 10, fields: [
      { name: 'option', type: 'text', required: true },
      { name: 'value', type: 'text', required: true },
    ] },
    { name: 'selectionKey', type: 'text', required: true, admin: { hidden: true }, access: { update: () => false } },
    { name: 'priceMinor', type: 'number', required: true, min: 0, validate: validateMinorAmount },
    { name: 'compareAtPriceMinor', type: 'number', min: 0, validate: validateMinorAmount },
    { name: 'stock', type: 'number', min: 0, validate: validateMinorAmount, admin: { description: 'Optional inventory count, not a reservation or order ledger.' } },
    { name: 'image', type: 'upload', relationTo: 'media' },
    { name: 'position', type: 'number', defaultValue: 0 },
    { name: 'published', type: 'checkbox', defaultValue: false },
  ],
  hooks: { ...hooks, beforeValidate: [async ({ data, originalDoc, req }) => {
    const merged = { ...originalDoc, ...data }
    for (const name of ['priceMinor', 'compareAtPriceMinor', 'stock']) {
      const result = validateMinorAmount(merged[name])
      if (result !== true) throw new Error(`${name}: ${result}`)
    }
    if (present(merged.compareAtPriceMinor) && merged.compareAtPriceMinor < merged.priceMinor) throw new Error('Compare-at price must not be below the variant price.')
    const productID = typeof merged.product === 'object' ? merged.product?.id : merged.product
    if (typeof productID !== 'number' && typeof productID !== 'string') throw new Error('Choose a product for this variant.')
    const product = await req.payload.findByID({ collection: 'products', id: productID, draft: true, depth: 0, req, overrideAccess: false })
    const validation = validateVariantSelection(product.options, merged.options)
    if (validation !== true) throw new Error(validation)
    const selectionKey = JSON.stringify((merged.options as unknown[]).map(row).map((item) => [item.option, item.value]).sort((a, b) => String(a[0]).localeCompare(String(b[0]), 'en')))
    return { ...data, selectionKey, sourceId: originalDoc?.sourceId || data?.sourceId || `variant:${globalThis.crypto.randomUUID()}` }
  }] },
})
