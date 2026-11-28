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

const routeGroups = ['(dashboard)', '(calendar)']

/**
 * Surfaces that are not part of the owner workspace yet or that depend on
 * tenant server code: the assistant review queue, server-redirect stubs, and
 * the tenant app's own auth/PWA/realtime shell. The calendar and booking
 * editor are the owner's, so they ship here; only their database modules stay
 * on the tenant.
 */
const excluded = [
  'src/app/(dashboard)/agent',
  'src/app/(dashboard)/import-export',
  'src/app/(dashboard)/rules',
  // The tenant's booking API is HelloAda's settings and type model, not the
  // upstream events model this editor expects. Shipping it would render a page
  // that cannot read its own data, so booking configuration stays out until its
  // own admin surface is generated from the HelloAda model.
  'src/app/(calendar)/booking',
  'src/lib/i18n/server.ts',
  'src/lib/cloudflare.ts',
  'src/db',
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
      const fromNext = new RegExp(`import\\s*\\{([^}]*)\\}\\s*from\\s*["']next/navigation["'];?`)
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

/**
 * The ported mailbox has no client session: the control plane owns the owner's
 * identity and this package never logs in. That left the session token as a
 * dead invalidation key — always null, so every "did the session change?" test
 * passed and the previous tenant's mailbox list stayed cached forever. The
 * tenant key replaces it as the only invalidation boundary.
 *
 * Every read and write of the token is removed rather than kept for a login
 * flow this package does not have.
 */
const patchDeadSessionToken = async (outputFile) => {
  let source = await readFile(outputFile, 'utf8')
  const blocks = [
    {
      label: 'client session token getter',
      pattern: /export function getClientSessionToken\(\): string \| null \{\n(?:.*\n)*?\}\n/,
    },
    {
      label: 'client session token setter',
      pattern: /export function setClientSessionToken\(token: string\): void \{\n(?:.*\n)*?\}\n/,
    },
    {
      label: 'client session token clearer',
      pattern: /export function clearClientSessionToken\(\): void \{\n(?:.*\n)*?\}\n/,
    },
    {
      label: 'persisted auth session',
      pattern: /export async function persistAuthSession\(response: Response\): Promise<AuthSessionResponse> \{\n(?:.*\n)*?\}\n/,
    },
  ]
  for (const { label, pattern } of blocks) {
    if (!pattern.test(source)) throw new Error(`Upstream auth client changed shape: ${label} is missing`)
    source = source.replace(pattern, '')
  }
  // The bearer header has no session to carry: the control plane injects the
  // tenant token on its side of the proxy.
  const tokenHeader = '\tconst token = getClientSessionToken();\n\tif (token && !nextHeaders.has("Authorization")) {\n\t\tnextHeaders.set("Authorization", `Bearer ${token}`);\n\t}\n'
  if (!source.includes(tokenHeader)) throw new Error('Upstream auth client changed shape: bearer header')
  source = source.replace(tokenHeader, '')
  if (/ClientSessionToken|persistAuthSession/.test(source)) {
    throw new Error('Generated auth client still exposes a client session')
  }
  await writeFile(outputFile, source)
}

/**
 * The mailbox has no login, no account switch and no sign-out: the control
 * plane owns the owner's identity. The upstream modules that served those are
 * removed from the tree rather than left as a second identity path, and no
 * generated file may import them.
 */
const removeDeadSessionModules = async (files) => {
  const dead = ['src/lib/auth/logout.ts', 'src/lib/auth/accounts-client.ts']
  for (const relative of dead) {
    const target = path.join(outputRoot, relative)
    if (await isFile(target)) await rm(target, { force: true })
  }
  for (const file of files) {
    const output = outputPathFor(file)
    if (!/\.(?:ts|tsx)$/.test(output) || !(await isFile(output))) continue
    const source = await readFile(output, 'utf8')
    if (!/auth\/(?:logout|accounts-client)/.test(source)) continue
    throw new Error(`${path.relative(outputRoot, output)} still imports a removed session module`)
  }
}

/**
 * Upstream renders a sidebar-bootstrap inline script from its root layout. That
 * layout is not part of the generated closure (the control plane supplies the
 * document), so the script was dead here — and as raw browser JavaScript it
 * bypassed the tenant-scoped storage façade that every other preference uses.
 * It is removed instead of kept in a second key format: the sidebar reads its
 * persisted width through the façade like the rest of the mailbox.
 */
const removeDeadSidebarBootstrap = async (outputFile) => {
  let source = await readFile(outputFile, 'utf8')
  const anchor = 'export const sidebarBootstrapScript'
  if (!source.includes(anchor)) return
  const start = source.indexOf(anchor)
  // Walk back over an attached block comment, then forward to the end of the template.
  let from = start
  const commentStart = source.lastIndexOf('/**', start)
  if (commentStart >= 0 && !source.slice(commentStart, start).includes('\n\nexport')) from = commentStart
  const end = source.indexOf('})();`;', start)
  if (end < 0) throw new Error('Upstream sidebar bootstrap changed shape: unterminated script')
  source = source.slice(0, from) + source.slice(end + '})();`;'.length)
  source = source.replace(/\nconst SIDEBAR_MINIMAL_STORAGE_KEY = "mailflare-sidebar-minimal";\n/, '\n')
  source = source.replace(/^\n+/, '')
  await writeFile(outputFile, source)
}

/**
 * A tenant's mailbox either reads or says so. The shell renders this gate in
 * place of the mailbox body, so an unprovisioned or failing tenant shows its own
 * setup state instead of an empty inbox, stale counts or another website's
 * address in the header.
 */
const writeMailboxGate = async () => {
  const source = `"use client";

import { useSelectedMailbox } from "./mailbox-provider";
import { useLanguage } from "./language-provider";

/**
 * The two failure states the mailbox can be in, kept apart on purpose: a tenant
 * whose mailbox is still being prepared is not the same as one whose read
 * failed, and an owner should not be told to wait for the second.
 */
export function MailboxGate({ children }: { children: React.ReactNode }) {
	const { isLoading, error } = useSelectedMailbox();
	const { t } = useLanguage();
	if (isLoading) return null;
	if (!error) return <>{children}</>;
	const setup = error.startsWith("mailbox_options_503");
	const title = setup ? t("mailbox.preparing.title") : t("mailbox.unavailable.title");
	const body = setup ? t("mailbox.preparing.body") : t("mailbox.unavailable.body");
	return (
		<div className="flex h-full items-center justify-center p-8">
			<div className="max-w-sm text-center">
				<h1 className="text-lg font-semibold text-neutral-900">{title}</h1>
				<p className="mt-2 text-sm text-neutral-600">{body}</p>
				<button
					type="button"
					onClick={() => location.reload()}
					className="mt-5 rounded-full bg-[#ff7a18] px-4 py-2 text-sm font-semibold text-neutral-900"
				>
					{t("mailbox.retry")}
				</button>
			</div>
		</div>
	);
}
`
  await writeFile(path.join(outputRoot, 'src/components/mailbox-gate.tsx'), source)
}

/**
 * The control plane owns the owner's identity, so the account menu has no
 * multi-account list, no account switch and no sign-out to perform: those are
 * authenticated session operations this package does not have. The menu keeps
 * the mailbox identity it is showing and the workspace routes beside it.
 */
const patchMailboxSelector = async (outputFile) => {
  let source = await readFile(outputFile, 'utf8')
  const edits = [
    ['import { logoutClientSession } from "../lib/auth/logout";\n', ''],
    ['import { fetchBrowserAccounts, switchBrowserAccount, type BrowserAccount } from "../lib/auth/accounts-client";\n', ''],
  ]
  for (const [before, after] of edits) {
    if (!source.includes(before)) throw new Error(`Upstream mailbox selector changed shape: ${before.trim().slice(0, 60)}`)
    source = source.replace(before, after)
  }
  const regions = [
    {
      label: 'browser account state and fetch',
      pattern: /\tconst \[browserAccounts, setBrowserAccounts\] = useState<BrowserAccount\[\]>\(\[\]\);\n\n\tuseEffect\(\(\) => \{\n\t\tif \(!open\) return;\n(?:.*\n)*?\t\}, \[open\]\);\n/,
    },
    { label: 'other accounts derivation', pattern: /\tconst otherAccounts = browserAccounts\.filter\(\(account\) => !account\.active && account\.userId !== user\?\.id\);\n/ },
    { label: 'logout handler', pattern: /\tasync function logout\(\) \{\n(?:.*\n)*?\t\}\n\n/ },
    { label: 'switch handler', pattern: /\tasync function switchAccount\(userId: string\) \{\n(?:.*\n)*?\t\}\n\n/ },
    {
      label: 'other accounts block',
      pattern: /\t\t\t\t\t\{otherAccounts\.length > 0 && \(\n(?:.*\n)*?\t\t\t\t\t\)\}\n\n/,
    },
    {
      label: 'add another account link',
      pattern: /\t\t\t\t\t\t<Link\n\t\t\t\t\t\t\thref="\/login\?add=1"\n(?:.*\n)*?\t\t\t\t\t\t<\/Link>\n/,
    },
    {
      label: 'sign out button',
      pattern: /\t\t\t\t\t\t<button\n\t\t\t\t\t\t\ttype="button"\n\t\t\t\t\t\t\tonClick=\{logout\}\n(?:.*\n)*?\t\t\t\t\t\t<\/button>\n/,
    },
  ]
  for (const { label, pattern } of regions) {
    if (!pattern.test(source)) throw new Error(`Upstream mailbox selector changed shape: ${label}`)
    source = source.replace(pattern, '')
  }
  for (const dead of [
    'logoutClientSession',
    'switchBrowserAccount',
    'fetchBrowserAccounts',
    'setBrowserAccounts',
    'browserAccounts',
    'otherAccounts',
    'BrowserAccount',
    '/login?add=1',
  ]) {
    if (source.includes(dead)) throw new Error(`Generated mailbox selector still carries the account session surface: ${dead}`)
  }
  await writeFile(outputFile, source)
}

/**
 * The mailbox list is the tenant's, so this provider is the one place that
 * decides what an owner sees when it cannot be read: an explicit setup or error
 * state, never a list left over from another website. The old swallow-and-keep
 * behaviour is what showed one tenant's identity under another tenant's site.
 */
const patchMailboxProvider = async (outputFile) => {
  let source = await readFile(outputFile, 'utf8')
  const load = /\tuseEffect\(\(\) => \{\n\t\tlet cancelled = false;\n\t\tconst sessionToken = getClientSessionToken\(\);\n\n\t\tfetchMailboxOptions\(\)\n(?:.*\n)*?\t\}, \[\]\);\n/
  if (!load.test(source)) throw new Error('Upstream mailbox provider changed shape: load effect')
  source = source.replace(
    load,
    `	useEffect(() => {
		let cancelled = false;

		fetchMailboxOptions()
			.then((items) => {
				if (cancelled) return;
				setError(null);
				setMailboxes(items);

				const storedId = mailboxStorage.getItem(SELECTED_MAILBOX_STORAGE_KEY);
				if (storedId) {
					const found = items.find((mb) => mb.id === storedId);
					if (found) {
						setSelectedMailboxState(found);
						return;
					}
				}

				const primary = items.find((mb) => mb.isPrimary) ?? items[0] ?? null;
				if (primary) {
					setSelectedMailboxState(primary);
					mailboxStorage.setItem(SELECTED_MAILBOX_STORAGE_KEY, primary.id);
				}
			})
			.catch((cause: unknown) => {
				if (cancelled) return;
				// Drop everything the previous render held: a failed read must not
				// leave another tenant's mailbox on screen.
				setMailboxes([]);
				setSelectedMailboxState(null);
				setError(cause instanceof Error ? cause.message : "mailbox_unavailable");
			})
			.finally(() => {
				if (!cancelled) setIsLoading(false);
			});

		return () => {
			cancelled = true;
		};
	}, []);
`,
  )
  const contextType = `type MailboxContextValue = {
	selectedMailbox: MailboxOption | null;
	setSelectedMailbox: (mb: MailboxOption | null) => void;
	mailboxes: MailboxOption[];
	isLoading: boolean;
};`
  if (!source.includes(contextType)) throw new Error('Upstream mailbox provider changed shape: context type')
  source = source.replace(
    contextType,
    `type MailboxContextValue = {
	selectedMailbox: MailboxOption | null;
	setSelectedMailbox: (mb: MailboxOption | null) => void;
	mailboxes: MailboxOption[];
	isLoading: boolean;
	/** Set when this tenant's mailbox could not be read; never a stale list. */
	error: string | null;
};`,
  )
  if (!source.includes('\tconst [isLoading, setIsLoading] = useState(true);\n')) {
    throw new Error('Upstream mailbox provider changed shape: loading state')
  }
  source = source.replace(
    '\tconst [isLoading, setIsLoading] = useState(true);\n',
    '\tconst [isLoading, setIsLoading] = useState(true);\n\tconst [error, setError] = useState<string | null>(null);\n',
  )
  const resetBlock = `		function resetMailboxState() {
			setMailboxes([]);
			setSelectedMailboxState(null);
			setIsLoading(true);
		}`
  if (!source.includes(resetBlock)) throw new Error('Upstream mailbox provider changed shape: reset handler')
  source = source.replace(
    resetBlock,
    `		function resetMailboxState() {
			setMailboxes([]);
			setSelectedMailboxState(null);
			setIsLoading(true);
			setError(null);
		}`,
  )
  const providerValue = '<MailboxContext.Provider value={{ selectedMailbox, setSelectedMailbox, mailboxes, isLoading }}>'
  if (!source.includes(providerValue)) throw new Error('Upstream mailbox provider changed shape: context value')
  source = source.replace(
    providerValue,
    '<MailboxContext.Provider value={{ selectedMailbox, setSelectedMailbox, mailboxes, isLoading, error }}>',
  )
  if (!/setError\(null\)/.test(source)) throw new Error('Generated mailbox provider never clears its error state')
  // The session-token import went with the session itself.
  const sessionImport = `import {
	AUTH_SESSION_CHANGED_EVENT,
	getClientSessionToken,
} from "../lib/auth/client";`
  if (!source.includes(sessionImport)) throw new Error('Upstream mailbox provider changed shape: auth session import')
  source = source.replace(sessionImport, 'import { AUTH_SESSION_CHANGED_EVENT } from "../lib/auth/client";')
  await writeFile(outputFile, source)
}


const patchTenantScopedCaches = async (hooksFile, providerUtilsFile) => {
  let hooks = await readFile(hooksFile, 'utf8')
  const listKey = '\tconst key = params.toString();'
  if (!hooks.includes(listKey)) throw new Error('Upstream message cache changed shape: list key')
  hooks = hooks.replace(listKey, '\tconst key = scopedCacheKey(params.toString());')
  const countsKey = '\tconst key = mailboxId ?? "all";'
  if (!hooks.includes(countsKey)) throw new Error('Upstream message cache changed shape: counts key')
  hooks = hooks.replace(countsKey, '\tconst key = scopedCacheKey(mailboxId ?? "all");')
  hooks = ensureImport(
    hooks,
    ['registerMailboxTenantReset', 'scopedCacheKey'],
    importSpecifier(path.relative(outputRoot, hooksFile).split(path.sep).join('/'), 'scope.ts'),
  )
  // Module caches outlive any component, so the reset has to be registered
  // once, at module scope, next to the caches themselves.
  const registration = `
registerMailboxTenantReset(() => {
	clearMessageClientState();
});
`
  hooks = hooks.replace(/\nconst messageCountsCache = /, `${registration}\nconst messageCountsCache = `)
  await writeFile(hooksFile, hooks)

  let provider = await readFile(providerUtilsFile, 'utf8')
  const cacheShape = /\nlet mailboxesCache: MailboxOption\[\] \| null = null;\nlet mailboxesCacheSessionToken: string \| null = null;\nlet mailboxesRequest: Promise<MailboxOption\[\]> \| null = null;\nlet mailboxesRequestSessionToken: string \| null = null;\nlet cacheGeneration = 0;\nexport const SELECTED_MAILBOX_STORAGE_KEY = "selected-mailbox-id";\n/
  if (!cacheShape.test(provider)) throw new Error('Upstream mailbox option cache changed shape')
  provider = provider.replace(
    cacheShape,
    `
let mailboxesCache: MailboxOption[] | null = null;
let mailboxesCacheTenantKey: string = "";
let cacheGeneration = 0;
export const SELECTED_MAILBOX_STORAGE_KEY = "selected-mailbox-id";

registerMailboxTenantReset(() => {
	clearMailboxesCache();
	mailboxStorage.removeItem(SELECTED_MAILBOX_STORAGE_KEY);
});
`,
  )
  provider = provider.replace(
    'import { authFetch, getClientSessionToken } from "../lib/auth/client";',
    `import { authFetch } from "../lib/auth/client";\nimport { mailboxStorage, mailboxTenantKey, registerMailboxTenantReset } from "${importSpecifier(
      path.relative(outputRoot, providerUtilsFile).split(path.sep).join('/'),
      'scope.ts',
    )}";`,
  )
  provider = provider.replace(
    /\texport function clearMailboxesCache/m,
    '\texport function clearMailboxesCache',
  )
  // The cache is valid for exactly one tenant.
  provider = provider.replace(
    `export function clearMailboxesCache() {
	cacheGeneration += 1;
	mailboxesCache = null;
	mailboxesCacheSessionToken = null;
	mailboxesRequest = null;
	mailboxesRequestSessionToken = null;
}`,
    `export function clearMailboxesCache() {
	cacheGeneration += 1;
	mailboxesCache = null;
	mailboxesCacheTenantKey = "";
}`,
  )
  provider = provider.replace(
    `	if (typeof window !== "undefined") {
		localStorage.removeItem(SELECTED_MAILBOX_STORAGE_KEY);
	}`,
    `	mailboxStorage.removeItem(SELECTED_MAILBOX_STORAGE_KEY);`,
  )
  provider = provider.replace(
    `export async function fetchMailboxOptions(force = false): Promise<MailboxOption[]> {
	const sessionToken = getClientSessionToken();
	if (!force && mailboxesCache && mailboxesCacheSessionToken === sessionToken) return mailboxesCache;
	if (!force && mailboxesRequest && mailboxesRequestSessionToken === sessionToken) return mailboxesRequest;

	const requestGeneration = cacheGeneration;
	mailboxesRequestSessionToken = sessionToken;
	mailboxesRequest = authFetch("/api/mailboxes")`,
    `export async function fetchMailboxOptions(force = false): Promise<MailboxOption[]> {
	const tenantKey = mailboxTenantKey();
	if (!force && mailboxesCache && mailboxesCacheTenantKey === tenantKey) return mailboxesCache;

	const requestGeneration = cacheGeneration;
	const request = authFetch("/api/mailboxes")`,
  )
  provider = provider.replace(
    `			if (requestGeneration === cacheGeneration) {
				mailboxesCache = items;
				mailboxesCacheSessionToken = sessionToken;
			}
			return items;
		})
		.finally(() => {
			if (requestGeneration === cacheGeneration) {
				mailboxesRequest = null;
				mailboxesRequestSessionToken = null;
			}
		});

	return mailboxesRequest;
}`,
    `			if (requestGeneration === cacheGeneration && mailboxTenantKey() === tenantKey) {
				mailboxesCache = items;
				mailboxesCacheTenantKey = tenantKey;
			}
			return items;
		});

	return request;
}`,
  )
  // A failed request must fail loudly: an unprovisioned tenant shows its setup
  // state, never the previous tenant's mailbox list.
  provider = provider.replace(
    `		.then((res) => res.json())
		.then((data) => {
			const items = ((data as { mailboxes?: MailboxOption[] }).mailboxes ?? []).map((m) => ({`,
    `		.then((res) => {
			if (!res.ok) throw new Error(\`mailbox_options_\${res.status}\`);
			return res.json() as Promise<{ mailboxes?: MailboxOption[] }>;
		})
		.then((data) => {
			const items = (data.mailboxes ?? []).map((m) => ({`,
  )
  if (/getClientSessionToken|mailboxesCacheSessionToken|mailboxesRequest/.test(provider)) {
    throw new Error('Generated mailbox option cache still keys on a session token')
  }
  await writeFile(providerUtilsFile, provider)
}

/**
 * Route every browser-storage read through the tenant-scoped façade.
 *
 * Upstream Mailflare keys preferences, the selected mailbox and the assistant
 * conversation on bare names because it owns its origin. HelloAda serves every
 * tenant from one origin, so each of those names has to carry the tenant. The
 * patch is a rename of the storage object, not a rewrite of the call sites: the
 * façade keeps `getItem`/`setItem`/`removeItem` and adds `keys()` for the two
 * modules that scan for `user:key` variants.
 */
const patchTenantScopedStorage = async (files) => {
  const scanned = files
    .map((file) => outputPathFor(file))
    .concat([
      path.join(outputRoot, 'index.tsx'),
      path.join(outputRoot, 'base.tsx'),
      path.join(outputRoot, 'scope.ts'),
    ])
  const touched = []
  for (const target of scanned) {
    if (!/\.(?:ts|tsx)$/.test(target)) continue
    // scope.ts owns the only real localStorage/sessionStorage references.
    if (target === path.join(outputRoot, 'scope.ts')) continue
    let source = await readFile(target, 'utf8')
    if (!/\b(?:window\.)?(?:localStorage|sessionStorage)\b/.test(source)) continue
    const before = source
    source = source
      .replace(/\bwindow\.localStorage\b/g, 'mailboxStorage')
      .replace(/\bwindow\.sessionStorage\b/g, 'mailboxSessionStorage')
      .replace(/\blocalStorage\b/g, 'mailboxStorage')
      .replace(/\bsessionStorage\b/g, 'mailboxSessionStorage')
    if (source === before) continue
    source = source.replace(/\bObject\.keys\(mailboxStorage\)/g, 'mailboxStorage.keys()')
    source = source.replace(/\bObject\.keys\(mailboxSessionStorage\)/g, 'mailboxSessionStorage.keys()')
    const relative = path.relative(outputRoot, target).split(path.sep).join('/')
    const names = []
    if (/\bmailboxStorage\b/.test(source)) names.push('mailboxStorage')
    if (/\bmailboxSessionStorage\b/.test(source)) names.push('mailboxSessionStorage')
    source = ensureImport(source, names, importSpecifier(relative, 'scope.ts'))
    await writeFile(target, source)
    touched.push(relative)
  }
  if (touched.length < 10) {
    throw new Error(`Tenant-scoped storage rewrite touched only ${touched.length} files: ${touched.join(', ')}`)
  }
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

  // The HelloAda control-plane header above the mailbox already carries the
  // brand mark and name. The vendor sidebar header keeps only its collapse
  // control, so the owner never sees a second mark, and there is no icon URL
  // that the control plane does not serve.
  const header = path.join(outputRoot, 'src/components/sidebar-header.tsx')
  let headerSource = await readFile(header, 'utf8')
  for (const [before, after] of [
    ['\tconst branding = useBranding();\n', ''],
    ['\t\t{minimal ? <img src={branding.iconUrl} height={32} width={32} alt="" /> : <TextAlignJustify size={18} />}', '\t\t<TextAlignJustify size={18} />'],
  ]) {
    if (!headerSource.includes(before)) throw new Error('Upstream sidebar header changed shape: ' + before)
    headerSource = headerSource.replace(before, after)
  }
  const brandLine = headerSource.split('\n').find((line) => line.includes('<img src={branding.iconUrl}'))
  if (!brandLine) throw new Error('Upstream sidebar header changed shape: brand row')
  headerSource = headerSource.replace(brandLine + '\n', '')
  headerSource = headerSource.replace(/^import \{ useBranding \} from "\.\/branding-provider";\n/m, '')
  headerSource = headerSource.replace(/^import Link from "next\/link";\n/m, '')
  headerSource = headerSource.replace(/^import \{ MailboxLink as Link \} from "[^"]+";\n/m, '')
  if (!headerSource.includes('export function SidebarHeader({ href, label }: SidebarHeaderProps) {')) {
    throw new Error('Upstream sidebar header changed shape: signature')
  }
  headerSource = headerSource.replace('export function SidebarHeader({ href, label }: SidebarHeaderProps) {', 'export function SidebarHeader(_props: SidebarHeaderProps) {')
  await writeFile(header, headerSource)

  // The mailbox body renders only once this tenant's mailbox has been read, so
  // a preparing or failing website never shows an empty or leftover inbox.
  const layoutFile = path.join(outputRoot, 'src/app/(dashboard)/layout.tsx')
  let layout = await readFile(layoutFile, 'utf8')
  const childrenAnchor = '                          {children}\n'
  if (!layout.includes(childrenAnchor)) throw new Error('Upstream dashboard layout changed shape: children')
  layout = layout.replace(childrenAnchor, '                          <MailboxGate>{children}</MailboxGate>\n')
  if (!layout.includes('import { MailboxProvider } from "../../components/mailbox-provider";')) {
    throw new Error('Upstream dashboard layout changed shape: mailbox provider import')
  }
  layout = layout.replace(
    'import { MailboxProvider } from "../../components/mailbox-provider";',
    'import { MailboxProvider } from "../../components/mailbox-provider";\nimport { MailboxGate } from "../../components/mailbox-gate";',
  )
  if (!layout.includes('<MailboxGate>{children}</MailboxGate>')) {
    throw new Error('Generated dashboard layout does not gate the mailbox body')
  }
  await writeFile(layoutFile, layout)
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

/**
 * The calendar layout offers a Calendar/Bookings switch. Only the calendar is
 * served here, so the booking tab and its route are removed rather than left
 * pointing at a page this package does not contain.
 */
const patchCalendarSections = async (outputFile) => {
  let source = await readFile(outputFile, 'utf8')
  const option = '<option value="/booking">{t("calendar.bookings")}</option>'
  if (source.split(option).length !== 2) throw new Error('Upstream calendar section switch changed shape: booking option')
  source = source.replace(option, '')
  const sectionValue = 'value={pathname === "/booking" ? "/booking" : "/calendar"}'
  if (source.split(sectionValue).length !== 2) throw new Error('Upstream calendar section switch changed shape: value')
  source = source.replace(sectionValue, 'value="/calendar"')
  const tab = /\s*<Link href="\/booking"[^>]*>\{t\("calendar\.bookings"\)\}<\/Link>/
  if (!tab.test(source)) throw new Error('Upstream calendar section switch changed shape: booking tab')
  source = source.replace(tab, '')
  if (source.includes('/booking')) throw new Error('Generated calendar layout still links to the booking editor')
  await writeFile(outputFile, source)
}

/**
 * Tenancy enters the mailbox client here and nowhere else.
 *
 * Upstream Mailflare is a single-deployment application: one origin, one
 * mailbox, one owner. HelloAda serves every tenant from one origin
 * (`helloada.app/<site>/mail`), so "one deployment" stopped being true while
 * every client key kept assuming it. This module makes the tenant the root of
 * every key the browser keeps: cache keys, localStorage keys and the reset
 * boundary between two tenants.
 *
 * It has no imports on purpose: the scope rules are testable on their own, and
 * `base.tsx` is the only place the React runtime sees them.
 */
const writeScope = async () => {
  const source = `
const STORAGE_PREFIX = "helloada-mailbox";

/** Keys written before tenancy existed. Ambiguous by construction, so removed. */
const LEGACY_KEY_PREFIXES = ["mailflare-", "selected-mailbox-id"];

let currentTenantKey = "";
const resetters = new Set<() => void>();
const legacyCleared = new Set<string>();

export function mailboxTenantKey(): string {
	return currentTenantKey;
}

export function mailboxStorageKey(name: string): string {
	return STORAGE_PREFIX + ":" + currentTenantKey + ":" + name;
}

/** Every client cache key is tenant-first, so two tenants cannot share an entry. */
export function scopedCacheKey(...parts: Array<string | null | undefined>): string {
	return [currentTenantKey, ...parts.map((part) => part ?? "")].join("|");
}

/**
 * Register a module-level cache to be dropped when the tenant changes. The
 * mailbox runtime is one instance per tenant, so crossing tenants resets it
 * wholesale instead of leaving the previous tenant's entries reachable.
 */
export function registerMailboxTenantReset(reset: () => void): void {
	resetters.add(reset);
}

/** Returns true when the tenant actually changed. */
export function setMailboxTenantKey(next: string): boolean {
	const normalized = next.trim();
	if (normalized === currentTenantKey) return false;
	currentTenantKey = normalized;
	for (const reset of resetters) reset();
	return true;
}

type StorageKind = "local" | "session";

function backingFor(kind: StorageKind): Storage | null {
	if (typeof window === "undefined") return null;
	try {
		return kind === "local" ? window.localStorage : window.sessionStorage;
	} catch {
		return null;
	}
}

/**
 * Drop the keys an earlier, tenant-less build wrote into this origin. They are
 * unreachable from the scoped namespace, but leaving them would keep one
 * tenant's preferences addressable under another tenant's names.
 */
function clearLegacyKeysOnce(kind: StorageKind, backing: Storage): void {
	const marker = kind + ":" + currentTenantKey;
	if (legacyCleared.has(marker)) return;
	legacyCleared.add(marker);
	const doomed: string[] = [];
	for (let index = 0; index < backing.length; index += 1) {
		const key = backing.key(index);
		if (!key || key.startsWith(STORAGE_PREFIX + ":")) continue;
		if (LEGACY_KEY_PREFIXES.some((prefix) => key.startsWith(prefix))) doomed.push(key);
	}
	for (const key of doomed) {
		try {
			backing.removeItem(key);
		} catch {
			// A blocked removal must not break the mailbox.
		}
	}
}

function createScopedStorage(kind: StorageKind) {
	return {
		getItem(name: string): string | null {
			const backing = backingFor(kind);
			if (!backing) return null;
			clearLegacyKeysOnce(kind, backing);
			try {
				return backing.getItem(mailboxStorageKey(name));
			} catch {
				return null;
			}
		},
		setItem(name: string, value: string): void {
			const backing = backingFor(kind);
			if (!backing) return;
			clearLegacyKeysOnce(kind, backing);
			try {
				backing.setItem(mailboxStorageKey(name), value);
			} catch {
				// Storage is unavailable in private windows; the session still works.
			}
		},
		removeItem(name: string): void {
			const backing = backingFor(kind);
			if (!backing) return;
			clearLegacyKeysOnce(kind, backing);
			try {
				backing.removeItem(mailboxStorageKey(name));
			} catch {
				// See setItem.
			}
		},
		/** The current tenant's key names, unprefixed, for the layout scans. */
		keys(): string[] {
			const backing = backingFor(kind);
			if (!backing) return [];
			clearLegacyKeysOnce(kind, backing);
			const prefix = STORAGE_PREFIX + ":" + currentTenantKey + ":";
			const names: string[] = [];
			try {
				for (let index = 0; index < backing.length; index += 1) {
					const key = backing.key(index);
					if (key && key.startsWith(prefix)) names.push(key.slice(prefix.length));
				}
			} catch {
				return names;
			}
			return names;
		},
	};
}

export const mailboxStorage = createScopedStorage("local");
export const mailboxSessionStorage = createScopedStorage("session");
`

  await writeFile(path.join(outputRoot, 'scope.ts'), source)
}

const writeBase = async () => {
  const source = `"use client";

import { createContext, useContext, useMemo, type ComponentProps, type ReactNode } from "react";
import NextLink from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { setMailboxTenantKey } from "./scope";

export {
	mailboxSessionStorage,
	mailboxStorage,
	mailboxStorageKey,
	mailboxTenantKey,
	registerMailboxTenantReset,
	scopedCacheKey,
} from "./scope";

/**
 * One mailbox runtime per tenant. The tenant key is required: a config without
 * it would put two websites back in one cache, which is the defect this
 * runtime exists to prevent.
 */
export type MailboxConfig = { apiBase: string; basePath: string; tenantKey: string };

let active: MailboxConfig = { apiBase: "/api", basePath: "", tenantKey: "" };

export function configureMailbox(config: MailboxConfig): void {
	if (!config.tenantKey || !config.tenantKey.trim()) {
		throw new Error("MailboxApp requires the tenant identity");
	}
	setMailboxTenantKey(config.tenantKey);
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
	// One runtime per tenant: configure first (it resets every cache when the
	// tenant changes), then key the query client so nothing from the previous
	// tenant's React state survives the switch either.
	configureMailbox(config);
	const normalized = path === "" ? "/" : path.replace(/\\/+$/, "");
	const matched = useMemo(() => matchRoute(normalized || "/", params), [normalized, params]);
	const [client] = useMemo(() => [new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 30_000 } } })], [config.tenantKey]);
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

/**
 * Two states the mailbox shell can render in place of its body. They belong to
 * every tenant, so they are added to the English catalogue once and translated
 * like the rest: an unknown key falls back to English rather than to a blank.
 */
const MAILBOX_GATE_COPY = {
  'mailbox.preparing.title': 'Your inbox is being prepared',
  'mailbox.preparing.body': 'HelloAda is setting up this website’s mailbox. It will open here as soon as setup finishes.',
  'mailbox.unavailable.title': 'Your inbox could not be opened',
  'mailbox.unavailable.body': 'This website’s mailbox did not answer. Nothing has been changed; try again in a moment.',
  'mailbox.retry': 'Try again',
}

const patchMailboxGateCopy = async (outputFile) => {
  const source = await readFile(outputFile, 'utf8')
  const parsed = JSON.parse(source)
  for (const [key, value] of Object.entries(MAILBOX_GATE_COPY)) {
    if (parsed[key] === undefined) parsed[key] = value
  }
  const sorted = Object.fromEntries(Object.entries(parsed).sort(([left], [right]) => left.localeCompare(right)))
  await writeFile(outputFile, `${JSON.stringify(sorted, null, 2)}\n`)
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
  const scopeFile = path.join(outputRoot, 'scope.ts')
  for (const output of outputs) {
    // A patch may have removed a module from the tree on purpose.
    if (!(await isFile(output))) continue
    const source = await readFile(output, 'utf8')
    const relative = path.relative(outputRoot, output)
    if (/from\s+["']@\//.test(source)) failures.push(`${relative}: unresolved alias import`)
    if (/fetch\(\s*["'`]\/api/.test(source)) failures.push(`${relative}: unprefixed /api fetch`)
    if (/window\.location\.assign\("\/login"\)/.test(source)) failures.push(`${relative}: login redirect`)
    if (/from\s+["']cloudflare:workers["']/.test(source)) failures.push(`${relative}: server-only Cloudflare module`)
    if (/from\s+["']next\/(?:headers|server)["']/.test(source)) failures.push(`${relative}: server-only Next module`)
    if (/\bAuthGuard\b/.test(source)) failures.push(`${relative}: tenant auth guard`)
    if (/\bh-dvh\b/.test(source)) failures.push(`${relative}: claims the whole viewport`)

    // Tenancy is the class this package exists to hold. `scope.ts` owns the only
    // real browser storage; everywhere else must go through its façade, or the
    // key is shared by every tenant on the origin. The one exception is the
    // inline sidebar bootstrap: it is stringified into the document before any
    // module loads, so it reads localStorage directly under a key it builds from
    // the tenant key.
    if (output !== scopeFile) {
      const directStorage = /\b(?:window\.)?(?:localStorage|sessionStorage)\b/.test(source)
      const isInlineBootstrap = relative.endsWith('sidebar-state-utils.ts')
        && source.includes('const prefix = "helloada-mailbox:" + tenantKey + ":";')
      if (directStorage && !isInlineBootstrap) {
        failures.push(`${relative}: unprefixed browser storage (bypasses scope.ts)`)
      }
    }
    if (/\bgetClientSessionToken\b/.test(source)) {
      failures.push(`${relative}: resolves a client session the ported mailbox does not have`)
    }
    // A cache key that is not tenant-first is the original defect.
    if (/const key = params\.toString\(\);/.test(source)) {
      failures.push(`${relative}: message list cache key omits the tenant`)
    }
    if (/const key = mailboxId \?\? "all";/.test(source)) {
      failures.push(`${relative}: message counts cache key omits the tenant`)
    }

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
  await patchDeadSessionToken(path.join(outputRoot, 'src/lib/auth/client.ts'))
  await patchMailboxSelector(path.join(outputRoot, 'src/components/mailbox-selector.tsx'))
  await patchMailboxProvider(path.join(outputRoot, 'src/components/mailbox-provider.tsx'))
  await patchTenantScopedCaches(
    path.join(outputRoot, 'src/hooks/utils.ts'),
    path.join(outputRoot, 'src/components/mailbox-provider-utils.ts'),
  )
  await patchStrictClientTypes(path.join(outputRoot, 'src/hooks/use-message-counts.ts'))
  await patchDraftDetail(path.join(outputRoot, 'src/app/(dashboard)/drafts/[messageId]/page.tsx'))
  await patchCalendarSections(path.join(outputRoot, 'src/app/(calendar)/layout.tsx'))
  await patchVendorTypes()
  await patchOwnerShell()
  await patchThreadStar(path.join(outputRoot, 'src/components/messages/thread-message-actions.tsx'))
  const localeFiles = await copyLocales()
  await patchLocaleCatalogs(path.join(outputRoot, 'src/lib/i18n/utils.ts'), localeFiles)
  await patchMailboxGateCopy(path.join(outputRoot, 'src/lib/i18n/en.json'))
  await writeMailboxGate()
  await writeBase()
  await writeScope()
  const pageCount = await buildRouteMap(files)
  await writeIndex(pageCount)
  await writeStyles()
  await patchTenantScopedStorage(files)
  // The sidebar's inline bootstrap script is raw browser JavaScript, so it is
  // repaired after the façade pass: it reads localStorage itself, under the
  // same tenant-scoped names.
  await removeDeadSidebarBootstrap(path.join(outputRoot, 'src/components/sidebar-state-utils.ts'))
  await applyBranding(files)
  await assertBranding(files)
  await removeDeadSessionModules(files)
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
