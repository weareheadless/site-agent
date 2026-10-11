function replaceExactlyOnce(source, before, after, label) {
  const first = source.indexOf(before)
  if (first < 0 || source.indexOf(before, first + before.length) >= 0) {
    throw new Error('Pinned Mailflare branding patch no longer applies exactly once: ' + label)
  }
  return source.slice(0, first) + after + source.slice(first + before.length)
}

function replaceLine(source, marker, replacement, label) {
  const lines = source.split('\n')
  const matches = lines.map((line, index) => line.includes(marker) ? index : -1).filter((index) => index >= 0)
  if (matches.length !== 1) throw new Error('Pinned Mailflare branding line is not unique: ' + label)
  lines[matches[0]] = replacement
  return lines.join('\n')
}

function removeLine(source, marker, label) {
  const lines = source.split('\n')
  const matches = lines.map((line, index) => line.includes(marker) ? index : -1).filter((index) => index >= 0)
  if (matches.length !== 1) throw new Error('Pinned Mailflare branding line is not unique: ' + label)
  lines.splice(matches[0], 1)
  return lines.join('\n')
}

function replaceSection(source, start, end, replacement, label) {
  const first = source.indexOf(start)
  const endAt = first < 0 ? -1 : source.indexOf(end, first + start.length)
  if (first < 0 || source.indexOf(start, first + start.length) >= 0 || endAt < 0) {
    throw new Error('Pinned Mailflare branding patch section is not unique: ' + label)
  }
  return source.slice(0, first) + replacement + '\n\n' + source.slice(endAt)
}

function replaceTail(source, start, replacement, label) {
  const first = source.indexOf(start)
  if (first < 0 || source.indexOf(start, first + start.length) >= 0 || !source.slice(first).trimEnd().endsWith('}')) {
    throw new Error('Pinned Mailflare branding patch tail is not unique: ' + label)
  }
  return source.slice(0, first) + replacement + '\n'
}

export function applyHelloAdaBrandingPatch(sources, basePath) {
  if (basePath !== '/mail') throw new Error('HelloAda branding requires the registered /mail base path')
  const iconPath = basePath + '/helloada-logo.svg'

  let layout = replaceExactlyOnce(sources.layout, 'title: "Mailflare",\n\tdescription: "Multi-tenant email on Cloudflare",', 'title: "HelloAda",\n\tdescription: "Multi-tenant email on Cloudflare",', 'document title')
  layout = replaceExactlyOnce(layout, 'description: "Multi-tenant email on Cloudflare",', 'description: "HelloAda business inbox, contacts and booking calendar",', 'document description')
  layout = replaceExactlyOnce(layout, 'icons: { icon: "/api/branding/icon", apple: "/icon-192.png" },', 'icons: { icon: "' + iconPath + '", apple: "' + iconPath + '" },', 'browser and Apple icons')
  layout = replaceExactlyOnce(layout, 'title: "Mailflare",', 'title: "HelloAda",', 'Apple web app title')
  layout = replaceExactlyOnce(layout, '<link rel="icon" href="/api/branding/icon"></link>', '<link rel="icon" href="' + iconPath + '" type="image/svg+xml"></link>', 'head favicon')

  let manifest = replaceExactlyOnce(sources.manifest, 'name: "Mailflare",\n\t\tshort_name: "Mailflare",', 'name: "HelloAda",\n\t\tshort_name: "Mailflare",', 'manifest name')
  manifest = replaceExactlyOnce(manifest, 'short_name: "Mailflare",', 'short_name: "HelloAda",', 'manifest short name')
  manifest = replaceExactlyOnce(manifest, 'description: "Email, anywhere.",', 'description: "HelloAda business inbox, contacts and booking calendar",', 'manifest description')
  manifest = replaceExactlyOnce(manifest, 'start_url: "/inbox",', 'start_url: "' + basePath + '/inbox",', 'manifest start URL')
  manifest = replaceExactlyOnce(
    manifest,
    'icons: [\n\t\t\t{ src: "/icon-192.png", sizes: "192x192", type: "image/png" },\n\t\t\t{ src: "/icon-512.png", sizes: "512x512", type: "image/png" },\n\t\t],',
    'icons: [{ src: "' + iconPath + '", sizes: "any", type: "image/svg+xml", purpose: "any" }],',
    'manifest icons',
  )

  const brandingDefaults = replaceExactlyOnce(
    sources.brandingDefaults,
    'appName: "Mailflare",',
    'appName: "HelloAda",',
    'default app name',
  )

  let brandingProvider = replaceExactlyOnce(sources.brandingProvider, 'document.title === "Mailflare"', 'document.title === "HelloAda"', 'document title refresh')
  brandingProvider = replaceLine(brandingProvider, 'iconUrl: branding.hasCustomIcon ?', '            iconUrl: "' + iconPath + '",', 'sidebar and booking icon')
  brandingProvider = removeLine(brandingProvider, 'const [iconVersion, setIconVersion]', 'custom icon version state')
  brandingProvider = removeLine(brandingProvider, 'setIconVersion(Date.now())', 'custom icon refresh')

  let brandingService = sources.brandingService
  brandingService = replaceExactlyOnce(brandingService, 'import { eq } from "drizzle-orm";\n', '', 'branding database import')
  brandingService = replaceExactlyOnce(brandingService, 'import { getDb } from "@/db";\n', '', 'branding database accessor')
  brandingService = replaceExactlyOnce(brandingService, 'import { appSettings } from "@/db/schema";\n', '', 'branding settings schema')
  brandingService = replaceExactlyOnce(brandingService, 'import { getLicenseEntitlements } from "@/lib/licenses/service";\n', '', 'branding entitlement import')
  brandingService = replaceExactlyOnce(
    brandingService,
    'export const APP_SETTINGS_ID = "default";\nexport const DEFAULT_APP_NAME = "Mailflare";\nexport const BRANDING_ICON_KEY = "branding/app-icon";',
    'export const DEFAULT_APP_NAME = "HelloAda";',
    'fixed platform brand',
  )
  brandingService = replaceSection(
    brandingService,
    'export async function getBranding(env: CloudflareEnv): Promise<Branding> {',
    'export async function updateBranding(',
    'export async function getBranding(_env: CloudflareEnv): Promise<Branding> {\n\treturn { appName: DEFAULT_APP_NAME, hasCustomIcon: false, canCustomizeBranding: false }\n}',
    'fixed branding read',
  )
  brandingService = replaceTail(
    brandingService,
    'export async function updateBranding(',
    'export async function updateBranding(_env: CloudflareEnv, _input: { appName: string; icon?: File | null }): Promise<Branding> {\n\tthrow new Error("HelloAda branding is fixed for this workspace")\n}',
    'disabled tenant branding mutation',
  )

  let sidebarFooter = replaceExactlyOnce(sources.sidebarFooter, 'import packageJson from "../../package.json";\\n', '', 'vendor version import')\n  sidebarFooter = replaceExactlyOnce(sidebarFooter, 'href={`https://mailflare.co/?ref=${typeof window !== "undefined" ? location.hostname : ""}&v=${packageJson.version}`}', 'href="https://helloada.app"', 'vendor footer link')\n  sidebarFooter = replaceExactlyOnce(sidebarFooter, 'Mailflare v{packageJson.version}', 'HelloAda', 'vendor footer label')\n\n  if (!sources.brandingIconRoute.includes('https://mailflare.local/icon-96.png')
      || !sources.brandingIconRoute.includes('export async function GET(request: Request)')) {
    throw new Error('Pinned Mailflare branding patch no longer recognizes the default icon route')
  }
  const brandingIconRoute = 'import { getEnvAsync } from "@/lib/cloudflare";\n\n'
    + 'export const dynamic = "force-dynamic";\nexport const revalidate = 0;\n\n'
    + 'export async function GET() {\n'
    + '\tconst env = await getEnvAsync();\n'
    + '\treturn env.ASSETS.fetch("https://mailflare.local' + iconPath + '");\n'
    + '}\n'

  return { layout, manifest, brandingDefaults, brandingProvider, brandingService, brandingIconRoute, sidebarFooter }
}

const replacedUpstreamBrandIcons = new Set([
  'public/favicon.ico',
  'public/icon-48.png',
  'public/icon-96.png',
  'public/icon-192.png',
  'public/icon-512.png',
])

export function shouldSkipUpstreamBrandIcon(relativePath) {
  return replacedUpstreamBrandIcons.has(relativePath)
}
