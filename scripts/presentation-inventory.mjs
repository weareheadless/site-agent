import { readdirSync } from 'node:fs'
import path from 'node:path'

const PAGE_FILES = new Set(['page.tsx', 'page.ts', 'page.jsx', 'page.js'])
// Directories that never publish an owner-facing page.
const PRIVATE_DIRECTORIES = new Set(['api', 'admin', 'helloada-preview', 'preview', 'node_modules'])

/**
 * Enumerate the public routes rendered by committed Next source.
 *
 * Route groups are transparent, private folders are skipped, and dynamic
 * segments are skipped because their concrete paths are data, not source.
 * The result is the inventory the owner workspace lists for a site whose
 * pages do not come from Payload documents.
 */
export const discoverPresentationRoutes = (appRoot) => {
  const visit = (directory, prefix) => {
    const routes = []
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const name = entry.name
      if (entry.isFile()) {
        if (PAGE_FILES.has(name)) routes.push(prefix || '/')
        continue
      }
      if (!entry.isDirectory()) continue
      if (name.startsWith('_') || name.startsWith('[') || PRIVATE_DIRECTORIES.has(name)) continue
      if (name.startsWith('(') && name.endsWith(')')) {
        routes.push(...visit(path.join(directory, name), prefix))
        continue
      }
      routes.push(...visit(path.join(directory, name), `${prefix}/${name}`))
    }
    return routes
  }
  const discovered = new Set(visit(appRoot, ''))
  return [...discovered].sort((left, right) => {
    if (left === '/') return -1
    if (right === '/') return 1
    return left.localeCompare(right)
  })
}

export const createPresentationInventory = (appRoot, previewMount) => {
  if (typeof previewMount !== 'string' || !previewMount.startsWith('/') || previewMount === '/' || previewMount.endsWith('/')) {
    throw new Error('The workspace preview mount must be an explicit absolute path without a trailing slash.')
  }
  return {
    schema: 1,
    previewMount,
    routes: discoverPresentationRoutes(appRoot).map((route) => ({ path: route })),
  }
}