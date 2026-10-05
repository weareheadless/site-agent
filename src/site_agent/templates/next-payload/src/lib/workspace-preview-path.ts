/** Workspace display aliases use the public renderer, never a second CMS reader.
 * Exact draft verification remains on the authenticated signed-token route.
 */
export function workspacePreviewPath(pathname: string, mount: string): string | undefined {
  if (!mount.startsWith('/') || mount === '/' || mount.endsWith('/')) {
    throw new Error('The workspace preview requires an explicit absolute mount.')
  }
  if (pathname === mount || pathname === `${mount}/`) return '/'
  if (!pathname.startsWith(`${mount}/`)) return undefined
  const path = pathname.slice(mount.length)
  // The preview alias must not provide a second entry point for platform APIs.
  if (/^\/(?:api|admin|_next|helloada-preview)(?:\/|$)/.test(path)) return undefined
  return path
}
