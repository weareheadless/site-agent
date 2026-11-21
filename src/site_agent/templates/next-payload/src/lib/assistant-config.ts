/**
 * The visitor assistant is declared in the tenant's own repository.
 *
 * ``src/site/assistant.json`` is tenant-owned content: the release generator
 * folds it into ``src/generated/helloada-assistant.json`` so a site that never
 * authored one simply ships ``{"enabled": false}``. Nothing here reads a
 * Site-Agent setting, and no tenant flag exists on the host.
 */
import generated from '../generated/helloada-assistant.json'

export type AssistantSources = 'site' | 'none'

export type AssistantConfig = {
  /** How the assistant should behave. Tenant-authored prose, never code. */
  purpose: string
  /** ``site`` grounds answers in the published site; ``none`` is persona only. */
  sources: AssistantSources
  /** Exact provider model id, chosen by the tenant for its own cost profile. */
  model: string
  /**
   * Answer against the accepted answer instead of from knowledge.
   *
   * This is the site's own writing, not a platform switch: a site whose voice is
   * wrong on purpose declares it here, and the platform records the accepted
   * answer before the turn so the persona has something concrete to be wrong
   * about. It requires ``sources: none`` — a site that answers from its own
   * pages cannot also answer against the record.
   */
  counterpoint: boolean
}

type GeneratedDeclaration = {
  enabled?: unknown
  purpose?: unknown
  sources?: unknown
  model?: unknown
  counterpoint?: unknown
}

export const assistantConfig = (): AssistantConfig | undefined => {
  const declaration = generated as GeneratedDeclaration
  if (declaration.enabled !== true) return undefined
  const purpose = String(declaration.purpose ?? '').trim()
  const model = String(declaration.model ?? '').trim()
  const sources = declaration.sources
  if (!purpose) throw new Error('Tenant assistant declaration has no purpose.')
  if (!model) throw new Error('Tenant assistant declaration has no model.')
  if (sources !== 'site' && sources !== 'none') {
    throw new Error('Tenant assistant declaration must declare sources as "site" or "none".')
  }
  const counterpoint = declaration.counterpoint === true
  if (counterpoint && sources !== 'none') {
    throw new Error('Tenant assistant declaration cannot set counterpoint with sources "site".')
  }
  return { purpose, sources, model, counterpoint }
}
