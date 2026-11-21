import { readFileSync } from 'node:fs'

/**
 * The visitor assistant is declared by the tenant in its own repository.
 *
 * A site that never authored ``src/site/assistant.json`` ships
 * ``{ enabled: false }``, so enabling the assistant is tenant content rather
 * than a host-side flag. An incomplete declaration is a build failure, never a
 * silently disabled assistant.
 */
export const readAssistantDeclaration = (declarationPath) => {
  let raw
  try {
    raw = readFileSync(declarationPath, 'utf8')
  } catch {
    return { enabled: false }
  }
  let declaration
  try {
    declaration = JSON.parse(raw)
  } catch (error) {
    throw new Error(`The tenant assistant declaration is not valid JSON: ${String(error?.message || error)}`)
  }
  if (!declaration || typeof declaration !== 'object' || Array.isArray(declaration)) {
    throw new Error('The tenant assistant declaration must be an object.')
  }
  const purpose = String(declaration.purpose ?? '').trim()
  const model = String(declaration.model ?? '').trim()
  if (!purpose) throw new Error('The tenant assistant declaration must state a purpose.')
  if (!model) throw new Error('The tenant assistant declaration must name a model.')
  if (declaration.sources !== 'site' && declaration.sources !== 'none') {
    throw new Error('The tenant assistant declaration must set sources to "site" or "none".')
  }
  if (declaration.counterpoint !== undefined && typeof declaration.counterpoint !== 'boolean') {
    throw new Error('The tenant assistant declaration must set counterpoint to true or false.')
  }
  const counterpoint = declaration.counterpoint === true
  if (counterpoint && declaration.sources !== 'none') {
    throw new Error('The tenant assistant declaration cannot set counterpoint with sources "site".')
  }
  return { enabled: true, purpose, sources: declaration.sources, model, counterpoint }
}
