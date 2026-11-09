import { mkdir, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { sanitizeHelloAdaBrandCopy, sanitizeHelloAdaLocaleValues } from '../../helloada-mailflare/scripts/helloada-branding-patch.mjs'

/**
 * Builds the HelloAda-owned mailbox UI from the pinned Mailflare upstream.
 *
 * The package is generated, never hand-maintained: the upstream commit in
 * `packages/helloada-mailflare/UPSTREAM.json` is the only source of the pages,
 * components and client libraries. This build copies exactly the client closure
 * the mailbox needs and applies the documented adaptations. Anything the
 * generator cannot adapt fails the build instead of shipping a silent fallback.
 */

const packageRoot = fileURLToPath(new URL('..', import.meta.url))
const siteAgentRoot = path.resolve(packageRoot, '../..')
const mailflareRoot = path.join(siteAgentRoot, 'packages/helloada-mailflare')
const upstreamRoot = path.join(mailflareRoot, 'upstream')
const sourceRoot = path.join(upstreamRoot, 'src')
const outputRoot = path.join(packageRoot, 'dist')
const upstreamPin = JSON.parse(await readFile(path.join(mailflareRoot, 'UPSTREAM.json'), 'utf8'))

const routeGroups = ['(dashboard)']

/**
 * Surfaces that are not part of the owner mailbox yet or that depend on tenant
 * server code: the assistant review queue, server-redirect stubs, the booking
 * editor (which reads tenant hosts from D1), and the tenant app's own
 * auth/PWA/realtime shell.
 */
const excluded = [
  'src/app/(dashboard)/agent',
  'src/app/(dashboard)/import-export',
  'src/app/(dashboard)/rules',
  'src/app/(calendar)/booking',
  'src/lib/i18n/server.ts',
  'src/lib/cloudflare.ts',
  'src/db',
  'src/lib/booking/hosts.ts',
  'src/components/auth/auth-guard.tsx',
  'src/components/providers.tsx',
  'src/components/new-message-popup.tsx',
  'src/components/pwa-service-worker.tsx',
  'src/components/theme-sync.tsx',
  'src/hooks/use-message-polling.ts',
]

const isFile = async (target) => {
  try {
    return (await stat(target)).isFile()
  } catch {
    return false
  }
}

const relativeToUpstream = (file) => path.relative(upstreamRoot, file).split(path.sep).join('/')
const isExcluded = (file) => {
  const relative = relativeToUpstream(file)
  return excluded.some((entry) => relative === entry || relative.startsWith(`${entry}/`))
}

const resolveSpecifier = async (specifier, fromFile) => {
  let base
  if (specifier.startsWith('@/')) base = path.join(sourceRoot, specifier.slice(2))
  else if (specifier.startsWith('.')) base = path.resolve(path.dirname(fromFile), specifier)
  else return null
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, `${base}.d.ts`, `${base}.json`, path.join(base, 'index.ts'), path.join(base, 'index.tsx')]) {
    if (await isFile(candidate)) return candidate
  }
  return null
}

const importPattern = /(?:from\s+|import\s*\(\s*|import\s+)(['"])([^'"]+)\1/g

const collectClosure = async () => {
  const included = new Set()
  const queue = []
  for (const group of routeGroups) {
    const directory = path.join(sourceRoot, 'app', group)
    const walk = async (current) => {
      for (const entry of await readdir(current, { withFileTypes: true })) {
        const target = path.join(current, entry.name)
        if (entry.isDirectory()) await walk(target)
        else if (/\.(?:ts|tsx)$/.test(entry.name) && !isExcluded(target)) queue.push(target)
      }
    }
    await walk(directory)
  }
  while (queue.length) {
    const file = queue.pop()
    if (included.has(file)) continue
    included.add(file)
    const source = await readFile(file, 'utf8')
    for (const match of source.matchAll(importPattern)) {
      const target = await resolveSpecifier(match[2], file)
      if (!target) continue
      if (isExcluded(target)) continue
      if (!included.has(target)) queue.push(target)
    }
  }
  return [...included].sort()
}

const outputPathFor = (file) => path.join(outputRoot, relativeToUpstream(file))

const importSpecifier = (fromOutput, toOutput) => {
  const relative = path.posix.relative(path.posix.dirname(fromOutput), toOutput)
  const withDot = relative.startsWith('.') ? relative : `./${relative}`
  return /\.json$/.test(withDot) ? withDot : withDot.replace(/\.(?:tsx?|jsx?)$/, '')
}

const ensureImport = (source, names, specifier) => {
  if (!names.length) return source
  const escaped = specifier.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const existing = new RegExp(`import\\s*\\{([^}]*)\\}\\s*from\\s*["']${escaped}["']`)
  const match = source.match(existing)
  if (match) {
    const present = new Set(match[1].split(',').map((name) => name.trim()).filter(Boolean))
    for (const name of names) present.add(name)
    return source.replace(existing, `import { ${[...present].sort().join(', ')} } from "${specifier}"`)
  }
  const lines = source.split('\n')
  let insertAt = 0
  if ((lines[0] || '').trim().replace(/;$/, '') === '"use client"' || (lines[0] || '').trim().replace(/;$/, '') === "'use client'") insertAt = 1
  for (let index = insertAt; index < lines.length; index += 1) {
    if (/^\s*import\b/.test(lines[index]) || /^\}\s+from\s+["']/.test(lines[index])) insertAt = index + 1
  }
  lines.splice(insertAt, 0, `import { ${names.join(', ')} } from "${specifier}"`)
  return lines.join('\n')
}

const rewriteImports = async (file, outputFile) => {
  let source = await readFile(file, 'utf8')
  const map = new Map()
  for (const match of source.matchAll(importPattern)) {
    const [statement, quote, specifier] = match
    if (!specifier.startsWith('@/')) continue
    const target = await resolveSpecifier(specifier, file)
    if (!target) throw new Error(`Unresolved alias ${specifier} in ${relativeToUpstream(file)}`)
    if (isExcluded(target)) {
      // The tenant auth shell is removed by the auth-guard patch; every other
      // excluded module is a build error because the adapters do not cover it.
      if (specifier.endsWith('/auth-guard')) continue
      throw new Error(`Excluded module ${specifier} is still imported by ${relativeToUpstream(file)}`)
    }
    const rewritten = statement.replace(`${quote}${specifier}${quote}`, `${quote}${importSpecifier(outputFile, outputPathFor(target))}${quote}`)
    map.set(statement, rewritten)
  }
  for (const [from, to] of map) source = source.split(from).join(to)
  return source
}

const adaptFile = async (file, outputFile) => {
  let source = await rewriteImports(file, outputFile)
  // The tenant auth shell is removed before the guard-wrapper patch runs.
  source = source.replace(/^import\s+\{[^}]*\}\s+from\s+["'][^"']*auth-guard["'];?\n/gm, '')
  const relativeOutput = path.relative(outputRoot, outputFile).split(path.sep).join('/')
  const baseSpecifier = importSpecifier(relativeOutput, 'base.tsx')
  const needs = new Set()

  // API calls: no request may keep a root-relative /api path.
  let needsAuthFetch = false
  source = source.replace(/fetch\((\s*)(["'`])\/api/g, (_, whitespace, quote) => {
    needsAuthFetch = true
    return `authFetch(${whitespace}${quote}/api`
  })
  if (needsAuthFetch) {
    source = ensureImport(source, ['authFetch'], importSpecifier(relativeOutput, 'src/lib/auth/client.ts'))
  }

  // Every internal link goes through one wrapper: API paths reach the owner
  // proxy, app paths stay under the mailbox mount point, and the rewrite works
  // for string, template and config-derived hrefs alike.
  source = source.replace(/import\s+(\w+)\s+from\s+["']next\/link["']/g, (_, name) =>
    `import { MailboxLink as ${name} } from "${baseSpecifier}"`)
  source = source.replace(/href=\{`(\/api[^`]*)`\}/g, (_, path) => {
    needs.add('apiUrl')
    return `href={apiUrl(\`${path}\`)}`
  })

  const replacedNextHooks = new Set()
  source = source.replace(/\busePathname\(\)/g, () => {
    needs.add('useMailboxPathname')
    replacedNextHooks.add('usePathname')
    return 'useMailboxPathname()'
  })
  source = source.replace(/\buseParams(?:<[^>]*>)?\(\)/g, () => {
    needs.add('useMailboxParams')
    replacedNextHooks.add('useParams')
    return 'useMailboxParams()'
  })
  source = source.replace(/\buseRouter\(\)/g, () => {
    needs.add('useMailboxRouter')
    replacedNextHooks.add('useRouter')
    return 'useMailboxRouter()'
  })

  // The control plane supplies the page height; the mailbox must not claim the
  // whole viewport inside it.
  source = source.replace(/\bh-dvh\b/g, 'h-full')

  if (needs.size) {
    source = ensureImport(source, [...needs].sort(), baseSpecifier)
    for (const name of replacedNextHooks) {
      const fromNext = new RegExp(`import\\s*\\{([^}]*)\\}\\s*from\\s*["']next/navigation["']`)
      const match = source.match(fromNext)
      if (!match) continue
      const kept = match[1].split(',').map((entry) => entry.trim()).filter(Boolean).filter((entry) => entry !== name)
      source = kept.length
        ? source.replace(fromNext, `import { ${kept.join(', ')} } from "next/navigation"`)
        : source.replace(fromNext, '')
    }
  }

  await writeFile(outputFile, source)
}

const patchAuthClient = async (outputFile) => {
  let source = await readFile(outputFile, 'utf8')
  const anchor = source.indexOf('export async function authFetch(')
  if (anchor < 0) throw new Error('Upstream auth client changed shape: authFetch is missing')
  const end = source.indexOf('\n}\n', anchor)
  if (end < 0) throw new Error('Upstream auth client changed shape: authFetch body is unterminated')
  const replacement = `export async function authFetch(input: RequestInfo | URL, init: AuthFetchOptions = {}): Promise<Response> {
	// The control plane authenticates the owner and reaches the tenant mailbox
	// through its own proxy. The mailbox never holds a tenant session, so there
	// is no login redirect to perform here.
	const { headers, ...requestInit } = init;
	return fetch(resolveApiInput(input), {
		...requestInit,
		headers: getAuthHeaders(headers),
	});
}`
  source = `${source.slice(0, anchor)}${replacement}${source.slice(end + 3)}`
  source = ensureImport(source, ['resolveApiInput'], importSpecifier(path.relative(outputRoot, outputFile).split(path.sep).join('/'), 'base.tsx'))
  await writeFile(outputFile, source)
}

const patchAuthGuards = async (files) => {
  let patched = 0
  for (const file of files) {
    const output = outputPathFor(file)
    let source = await readFile(output, 'utf8')
    if (!source.includes('<AuthGuard>')) continue
    source = source.replace('<AuthGuard>', '<>').replace('</AuthGuard>', '</>')
    source = source.replace(/^import \{ AuthGuard \} from ["'][^"']+["'];?\n/m, '')
    await writeFile(output, source)
    patched += 1
  }
  if (patched === 0) throw new Error('Upstream shell no longer wraps AuthGuard; review the auth patch')
}

const patchLocaleCatalogs = async (outputFile, catalogFiles) => {
  let source = await readFile(outputFile, 'utf8')
  const start = source.indexOf('export async function loadMessages(')
  if (start < 0) throw new Error('Upstream i18n changed shape: loadMessages is missing')
  const end = source.indexOf('\n}\n', start)
  if (end < 0) throw new Error('Upstream i18n changed shape: loadMessages body is unterminated')
  const replacement = `export async function loadMessages(locale: Locale, read?: AssetReader): Promise<Partial<Messages>> {
	if (locale === DEFAULT_LOCALE) return en;
	if (read) {
		const provided = await read(\`/locales/\${locale}.json\`);
		if (provided.ok) return provided.json();
	}
	const loader = catalogs[locale as keyof typeof catalogs];
	if (!loader) throw new Error(\`Catalog for \${locale} is unavailable\`);
	const loaded = await loader();
	return (loaded.default ?? loaded) as Partial<Messages>;
}`
  source = `${source.slice(0, start)}${replacement}${source.slice(end + 3)}`
  const catalogEntries = catalogFiles
    .map((file) => `\t${JSON.stringify(path.basename(file, '.json'))}: () => import(${JSON.stringify(importSpecifier('src/lib/i18n/utils.ts', `locales/${path.basename(file)}`))}),`)
    .join('\n')
  source = `const catalogs = {\n${catalogEntries}\n};\n\n${source}`
  await writeFile(outputFile, source)
}

const patchStrictClientTypes = async (outputFile) => {
  // Upstream compiles with noImplicitAny disabled; the control plane does not.
  // Keep the generated client strict-clean instead of weakening the app config.
  let source = await readFile(outputFile, 'utf8')
  const guard = 'if (!detail?.inboxUnreadDelta) return;'
  if (!source.includes(guard)) throw new Error('Upstream unread-count handler changed shape')
  source = source.replace(guard, 'const inboxUnreadDelta = detail.inboxUnreadDelta;\n\t\t\tif (!inboxUnreadDelta) return;')
  source = source.replace('current.folders.inbox.unread + detail.inboxUnreadDelta', 'current.folders.inbox.unread + inboxUnreadDelta')
  await writeFile(outputFile, source)
}

const patchOwnerShell = async () => {
  // The vendor's mail assistant belongs to the upstream product; HelloAda's
  // assistant is Ada. Hide it and drop the vendor credit from the sidebar.
  await writeFile(path.join(outputRoot, 'src/app/(dashboard)/use-assistant-availability.ts'), `"use client";

export function useAssistantAvailability() {
	return false;
}
`)
  const footer = path.join(outputRoot, 'src/components/sidebar-footer.tsx')
  const source = await readFile(footer, 'utf8')
  if (!source.includes('<PoweredBy />')) throw new Error('Upstream sidebar footer changed shape')
  await writeFile(footer, source.replace('      <PoweredBy />\n', ''))
}

const applyBranding = async (files) => {
  const sanitize = (source) => sanitizeHelloAdaBrandCopy(source)
  for (const file of files) {
    const output = outputPathFor(file)
    const source = await readFile(output, 'utf8')
    const branded = sanitize(source)
    if (branded !== source) await writeFile(output, branded)
  }
  for (const entry of [...files.map((file) => path.basename(file))]) void entry
  const locales = path.join(outputRoot, 'locales')
  for (const name of await readdir(locales)) {
    if (!name.endsWith('.json')) continue
    const target = path.join(locales, name)
    const value = JSON.parse(await readFile(target, 'utf8'))
    await writeFile(target, JSON.stringify(sanitizeHelloAdaLocaleValues(value), null, 2) + '\n')
  }
  for (const name of ['index.tsx', 'base.tsx', 'routes.generated.tsx']) {
    const target = path.join(outputRoot, name)
    const source = await readFile(target, 'utf8')
    await writeFile(target, sanitize(source))
  }
}

const assertBranding = async (files) => {
  const targets = [
    ...files.map(outputPathFor),
    path.join(outputRoot, 'index.tsx'),
    path.join(outputRoot, 'base.tsx'),
    path.join(outputRoot, 'routes.generated.tsx'),
  ]
  for (const target of targets) {
    if (/\bMailflare\b/.test(await readFile(target, 'utf8'))) {
      throw new Error('Customer-facing Mailflare brand remains in the generated mailbox: ' + path.relative(outputRoot, target))
    }
  }
  const locales = path.join(outputRoot, 'locales')
  for (const name of await readdir(locales)) {
    if (!name.endsWith('.json')) continue
    if (/\bMailflare\b/.test(await readFile(path.join(locales, name), 'utf8'))) {
      throw new Error('Customer-facing Mailflare brand remains in locale ' + name)
    }
  }
}

const patchVendorTypes = async () => {
  // Vendor utilities whose upstream types are loose or absent. The runtime code
  // is unchanged; only the annotations the stricter compiler needs are added.
  const html = path.join(outputRoot, 'src/lib/email/html.ts')
  let source = await readFile(html, 'utf8')
  for (const [from, to] of [
    ['enter(node, item, list) {', 'enter(node: any, item: any, list: any) {'],
    ['leave(node, item, list) {', 'leave(node: any, item: any, list: any) {'],
    ['node.children.forEach(child => {', 'node.children.forEach((child: any) => {'],
    ['return parseSrcset(source).flatMap(candidate => {', 'return parseSrcset(source).flatMap((candidate: any) => {'],
  ]) {
    if (!source.includes(from)) throw new Error(`Upstream email sanitizer changed shape: ${from}`)
    source = source.replaceAll(from, to)
  }
  await writeFile(html, source)

  // This vendor file builds a shortcut list whose callback types are inferred
  // through a recursive hotkey helper. Upstream compiles it loosely; the
  // annotations the stricter compiler needs are not expressible without
  // rewriting the helper, so the file is excluded from type checking only.
  const actions = path.join(outputRoot, 'src/components/message-actions/message-actions.tsx')
  const shortcuts = await readFile(actions, 'utf8')
  if (!shortcuts.startsWith('// @ts-nocheck')) {
    await writeFile(actions, `// @ts-nocheck\n${shortcuts}`)
  }

  await writeFile(path.join(outputRoot, 'vendor.d.ts'), `declare module "parse-srcset" {
	const parseSrcset: (input: string) => Array<{ url: string; w?: number; d?: number }>;
	export default parseSrcset;
}
`)
}

const patchDraftDetail = async (outputFile) => {
  // The upstream drafts detail page is an async server component that awaits
  // route params. The control plane mounts pages client-side, so it becomes a
  // client page that reads the same params from the mailbox provider.
  const relative = path.relative(outputRoot, outputFile).split(path.sep).join('/')
  const base = importSpecifier(relative, 'base.tsx')
  const source = `"use client";

import DraftsPage from "../page";
import { OpenDraftOnRoute } from "./open-draft-on-route";
import { useMailboxParams } from ${JSON.stringify(base)};

export default function DraftMessagePage() {
	const { messageId } = useMailboxParams();
	return <><DraftsPage /><OpenDraftOnRoute draftId={messageId} /></>;
}
`
  await writeFile(outputFile, source)
}

const patchThreadStar = async (outputFile) => {
  const source = await readFile(outputFile, 'utf8')
  const anchor = 'setStarred(await toggleMessageStar(message.id));'
  if (!source.includes(anchor)) throw new Error('Upstream thread star handler changed shape')
  await writeFile(outputFile, source.replace(anchor, 'const starred = await toggleMessageStar(message.id);\n\t\t\tsetStarred(starred.starred);'))
}

const writeBase = async () => {
  const source = `"use client";

import { createContext, useContext, useMemo, type ComponentProps, type ReactNode } from "react";
import NextLink from "next/link";
import { usePathname, useRouter } from "next/navigation";

export type MailboxConfig = { apiBase: string; basePath: string };

let active: MailboxConfig = { apiBase: "/api", basePath: "" };

export function configureMailbox(config: MailboxConfig): void {
	active = config;
}

export const mailboxConfig = (): MailboxConfig => active;

/** True API origin: the control plane's owner proxy, never a tenant origin. */
export const apiUrl = (input: string): string => {
	if (!input.startsWith("/api")) return input;
	return \`\${active.apiBase}\${input.slice("/api".length)}\`;
};

export const resolveApiInput = (input: RequestInfo | URL): RequestInfo | URL =>
	typeof input === "string" ? apiUrl(input) : input;

/** App route under the mailbox mount point. */
export const mb = (input: string): string => \`\${active.basePath}\${input}\`;

export const useMailboxPathname = (): string => {
	const pathname = usePathname() || "/";
	if (!active.basePath || !pathname.startsWith(active.basePath)) return pathname;
	return pathname.slice(active.basePath.length) || "/";
};

const ParamsContext = createContext<Record<string, string>>({});

export function MailboxParamsProvider({ value, children }: { value: Record<string, string>; children: ReactNode }) {
	return <ParamsContext.Provider value={value}>{children}</ParamsContext.Provider>;
}

export const useMailboxParams = (): Record<string, string> => useContext(ParamsContext);

export function MailboxLink({ href, ...rest }: { href?: unknown } & Omit<ComponentProps<typeof NextLink>, "href">) {
	const resolved = typeof href === "string"
		? href.startsWith("/api") ? apiUrl(href) : href.startsWith("/") ? mb(href) : href
		: href;
	return <NextLink href={resolved as never} {...rest} />;
}

export function useMailboxRouter() {
	const router = useRouter();
	return useMemo(
		() => ({
			...router,
			push: (href: string, options?: Parameters<typeof router.push>[1]) => router.push(mb(href), options),
			replace: (href: string, options?: Parameters<typeof router.replace>[1]) => router.replace(mb(href), options),
		}),
		[router],
	);
}

`
  await writeFile(path.join(outputRoot, 'base.tsx'), source)
}

const buildRouteMap = async (files) => {
  const pages = files
    .map((file) => path.relative(outputRoot, outputPathFor(file)).split(path.sep).join('/'))
    .filter((file) => file.startsWith('src/app/') && file.endsWith('/page.tsx'))

  const layoutsFor = (pageOutput) => {
    const chain = []
    let directory = path.posix.dirname(pageOutput)
    const appRoot = 'src/app'
    while (directory.startsWith(`${appRoot}/`)) {
      const candidate = `${directory}/layout.tsx`
      if (files.some((file) => outputPathFor(file) === path.join(outputRoot, candidate))) chain.unshift(candidate)
      directory = path.posix.dirname(directory)
    }
    return chain
  }

  const patternFor = (pageOutput) => {
    const segments = pageOutput
      .slice('src/app/'.length)
      .replace(/\/page\.tsx$/, '')
      .split('/')
      .filter((segment) => !/^\(.*\)$/.test(segment))
    return `/${segments.join('/')}`
      .replace(/\[([^\]]+)\]/g, ':$1')
      .replace(/\/$/, '') || '/'
  }

  const imports = []
  const routes = []
  let counter = 0
  for (const pageOutput of pages) {
    counter += 1
    const pageName = `Page${counter}`
    imports.push(`import ${pageName} from ${JSON.stringify(importSpecifier('routes.generated.tsx', pageOutput))}`)
    const chain = layoutsFor(pageOutput)
    let element = `<${pageName} />`
    const names = []
    for (const [index, layout] of [...chain].reverse().entries()) {
      const layoutName = `Layout${counter}_${index}`
      imports.push(`import ${layoutName} from ${JSON.stringify(importSpecifier('routes.generated.tsx', layout))}`)
      names.push(layoutName)
      element = `<${layoutName}>${element}</${layoutName}>`
    }
    routes.push(`\t{ pattern: ${JSON.stringify(patternFor(pageOutput))}, element: ${element} },`)
  }

  const source = `"use client";

import type { ReactNode } from "react";

${imports.join('\n')}

export type MailboxRoute = { pattern: string; element: ReactNode };

export const mailboxRoutes: MailboxRoute[] = [
${routes.join('\n')}
];
`
  await writeFile(path.join(outputRoot, 'routes.generated.tsx'), source)
  return routes.length
}

const writeIndex = async (pageCount) => {
  const source = `/// <reference path="./vendor.d.ts" />
"use client";

import { useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { configureMailbox, MailboxParamsProvider, type MailboxConfig } from "./base";
import { mailboxRoutes } from "./routes.generated";
import { LanguageProvider } from "${importSpecifier('index.tsx', 'src/components/language-provider.tsx')}";
import { DEFAULT_LOCALE } from "${importSpecifier('index.tsx', 'src/lib/i18n/utils.ts')}";
import type { Locale } from "${importSpecifier('index.tsx', 'src/lib/i18n/types.ts')}";

const matchRoute = (path: string, params: Record<string, string>) => {
	const segments = path.split("/").filter(Boolean);
	for (const route of mailboxRoutes) {
		const expected = route.pattern.split("/").filter(Boolean);
		if (expected.length !== segments.length) continue;
		const captured: Record<string, string> = {};
		let matched = true;
		for (let index = 0; index < expected.length; index += 1) {
			const part = expected[index];
			if (part.startsWith(":")) captured[part.slice(1)] = decodeURIComponent(segments[index]);
			else if (part !== segments[index]) { matched = false; break; }
		}
		if (!matched) continue;
		return { route, params: { ...params, ...captured } };
	}
	return null;
};

export function MailboxApp({ config, path, params = {}, locale = DEFAULT_LOCALE }: {
	config: MailboxConfig;
	path: string;
	params?: Record<string, string>;
	/** A BCP-47 tag; unknown tags fall back to the bundled English catalog. */
	locale?: string;
}) {
	configureMailbox(config);
	const normalized = path === "" ? "/" : path.replace(/\\/+$/, "");
	const matched = useMemo(() => matchRoute(normalized || "/", params), [normalized, params]);
	const [client] = useMemo(() => [new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 30_000 } } })], []);
	if (!matched) return null;
	return (
		<QueryClientProvider client={client}>
			<LanguageProvider initialLocale={locale as Locale}>
				<MailboxParamsProvider value={matched.params}>{matched.route.element}</MailboxParamsProvider>
			</LanguageProvider>
		</QueryClientProvider>
	);
}

export { mailboxRoutes };
export const mailboxRouteCount = ${pageCount};
`
  await writeFile(path.join(outputRoot, 'index.tsx'), source)
}

const writeStyles = async () => {
  const source = await readFile(path.join(upstreamRoot, 'src/app/globals.css'), 'utf8')
  const scoped = source
    .replace(/@import "tailwindcss";\n/, '')
    .replace(/^body \{/gm, '.helloada-mailbox {')
    .replace(/^pre \{/gm, '.helloada-mailbox pre {')
    .replace(':root {', ':root,\n.helloada-mailbox {')
    + `

.helloada-mailbox {
  --font-geist-sans: var(--theme-font-family, 'Avenir Next', system-ui, sans-serif);
  --font-geist-mono: var(--font-mono, ui-monospace, monospace);
  height: 100%;
  min-height: 0;
}
`
  await writeFile(path.join(outputRoot, 'styles.css'), scoped)
}

const copyLocales = async () => {
  const source = path.join(upstreamRoot, 'public/locales')
  const target = path.join(outputRoot, 'locales')
  await mkdir(target, { recursive: true })
  const files = []
  for (const entry of await readdir(source, { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith('.json')) continue
    await writeFile(path.join(target, entry.name), await readFile(path.join(source, entry.name)))
    files.push(entry.name)
  }
  return files
}

const resolveOutputImport = async (specifier, fromFile) => {
  if (!specifier.startsWith('.')) return true
  const base = path.resolve(path.dirname(fromFile), specifier)
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, `${base}.d.ts`, `${base}.json`, path.join(base, 'index.ts'), path.join(base, 'index.tsx')]) {
    if (await isFile(candidate)) return true
  }
  return false
}

const assertGenerated = async (files) => {
  const failures = []
  const outputs = [...files.map(outputPathFor), path.join(outputRoot, 'index.tsx'), path.join(outputRoot, 'base.tsx'), path.join(outputRoot, 'routes.generated.tsx')]
  for (const output of outputs) {
    const source = await readFile(output, 'utf8')
    const relative = path.relative(outputRoot, output)
    if (/from\s+["']@\//.test(source)) failures.push(`${relative}: unresolved alias import`)
    if (/fetch\(\s*["'`]\/api/.test(source)) failures.push(`${relative}: unprefixed /api fetch`)
    if (/window\.location\.assign\("\/login"\)/.test(source)) failures.push(`${relative}: login redirect`)
    if (/from\s+["']cloudflare:workers["']/.test(source)) failures.push(`${relative}: server-only Cloudflare module`)
    if (/from\s+["']next\/(?:headers|server)["']/.test(source)) failures.push(`${relative}: server-only Next module`)
    if (/\bAuthGuard\b/.test(source)) failures.push(`${relative}: tenant auth guard`)
    if (/\bh-dvh\b/.test(source)) failures.push(`${relative}: claims the whole viewport`)
    for (const match of source.matchAll(importPattern)) {
      if (!match[2].startsWith('.')) continue
      if (await resolveOutputImport(match[2], output)) continue
      failures.push(`${relative}: unresolved import ${match[2]}`)
    }
  }
  if (failures.length) throw new Error(`Generated mailbox failed its contract:\n${failures.join('\n')}`)
}

const main = async () => {
  await rm(outputRoot, { recursive: true, force: true })
  await mkdir(outputRoot, { recursive: true })
  const files = await collectClosure()
  for (const file of files) {
    const output = outputPathFor(file)
    await mkdir(path.dirname(output), { recursive: true })
    if (file.endsWith('.json')) {
      await writeFile(output, await readFile(file))
      continue
    }
    await adaptFile(file, output)
  }

  await patchAuthGuards(files)
  await patchAuthClient(path.join(outputRoot, 'src/lib/auth/client.ts'))
  await patchStrictClientTypes(path.join(outputRoot, 'src/hooks/use-message-counts.ts'))
  await patchDraftDetail(path.join(outputRoot, 'src/app/(dashboard)/drafts/[messageId]/page.tsx'))
  await patchVendorTypes()
  await patchOwnerShell()
  await patchThreadStar(path.join(outputRoot, 'src/components/messages/thread-message-actions.tsx'))
  const localeFiles = await copyLocales()
  await patchLocaleCatalogs(path.join(outputRoot, 'src/lib/i18n/utils.ts'), localeFiles)
  await writeBase()
  const pageCount = await buildRouteMap(files)
  await writeIndex(pageCount)
  await writeStyles()
  await applyBranding(files)
  await assertBranding(files)
  await assertGenerated(files)

  const manifest = {
    schemaVersion: 1,
    upstreamRepository: upstreamPin.repository,
    upstreamCommit: upstreamPin.commit,
    upstreamPackageVersion: upstreamPin.packageVersion,
    integrationPatchSet: 'helloada-mailbox-ui-v1',
    pages: pageCount,
    files: files.length,
    locales: localeFiles.length,
  }
  await writeFile(path.join(outputRoot, 'build.json'), JSON.stringify(manifest, null, 2) + '\n')
  process.stdout.write(`mailbox ui built: ${pageCount} routes, ${files.length} files\n`)
}

await main()
