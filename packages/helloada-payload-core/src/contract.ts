import { createHash } from 'node:crypto'

import { createHelloAdaContentContract, HELLOADA_CAPABILITIES } from './schema/index.ts'

export type HelloAdaContractSelection = {
  collections?: readonly string[]
  globals?: readonly string[]
  locales: readonly string[]
  defaultLocale: string
}

const normalize = (values: readonly string[], allowed: readonly string[], label: string) => {
  const result = [...new Set(values)].sort()
  const unsupported = result.filter((value) => !allowed.includes(value))
  if (unsupported.length) throw new Error(`Unsupported HelloAda ${label}: ${unsupported.join(', ')}`)
  return result
}

/**
 * Deterministic identities for one platform schema and one tenant's selections.
 * Locale selection is deployment configuration, not a database schema change.
 */
export const createHelloAdaContractIdentity = (selection: HelloAdaContractSelection) => {
  const contentContract = createHelloAdaContentContract()
  const selectedCollections = normalize(selection.collections || HELLOADA_CAPABILITIES.collections, HELLOADA_CAPABILITIES.collections, 'collections')
  const selectedGlobals = normalize(selection.globals || HELLOADA_CAPABILITIES.globals, HELLOADA_CAPABILITIES.globals, 'globals')
  const schemaShape = {
    contract: HELLOADA_CAPABILITIES.contract,
    schemaRevision: HELLOADA_CAPABILITIES.schemaRevision,
    collections: Object.fromEntries(selectedCollections.map((slug) => [slug, [...contentContract.collections[slug]].sort()])),
    globals: Object.fromEntries(selectedGlobals.map((slug) => [slug, [...contentContract.globals[slug]].sort()])),
    contentBlocks: [...contentContract.contentBlocks].sort(),
  }
  const locales = [...new Set(selection.locales)].sort()
  const configuration = {
    ...schemaShape,
    locales,
    defaultLocale: selection.defaultLocale,
  }
  if (!locales.length || !locales.includes(selection.defaultLocale)) {
    throw new Error('The HelloAda default locale must be included in the enabled locales.')
  }
  const normalizedSchema = JSON.stringify(schemaShape)
  const normalizedConfiguration = JSON.stringify(configuration)
  return {
    ...configuration,
    schemaIdentity: createHash('sha256').update(normalizedSchema).digest('hex'),
    configurationIdentity: createHash('sha256').update(normalizedConfiguration).digest('hex'),
  }
}
