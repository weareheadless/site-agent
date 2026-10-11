function replaceExactlyOnce(source, before, after, label) {
  const first = source.indexOf(before)
  if (first < 0 || source.indexOf(before, first + before.length) >= 0) {
    throw new Error('Pinned Mailflare branding patch no longer applies exactly once: ' + label)
  }
  return source.slice(0, first) + after + source.slice(first + before.length)
}

function replaceLine(source, marker, replacement, label) {
  const lines = source.split(String.fromCharCode(10))
  const matches = lines.map((line, index) => line.includes(marker) ? index : -1).filter((index) => index >= 0)
  if (matches.length !== 1) throw new Error('Pinned Mailflare branding line is not unique: ' + label)
  lines[matches[0]] = replacement
  return lines.join(String.fromCharCode(10))
}

function removeLine(source, marker, label) {
  const lines = source.split(String.fromCharCode(10))
  const matches = lines.map((line, index) => line.includes(marker) ? index : -1).filter((index) => index >= 0)
  if (matches.length !== 1) throw new Error('Pinned Mailflare branding line is not unique: ' + label)
  lines.splice(matches[0], 1)
  return lines.join(String.fromCharCode(10))
}

function replaceSection(source, start, end, replacement, label) {
  const first = source.indexOf(start)
  const endAt = first < 0 ? -1 : source.indexOf(end, first + start.length)
  if (first < 0 || source.indexOf(start, first + start.length) >= 0 || endAt < 0) {
    throw new Error('Pinned Mailflare branding patch section is not unique: ' + label)
  }
  return source.slice(0, first) + replacement + String.fromCharCode(10, 10) + source.slice(endAt)
}

function replaceTail(source, start, replacement, label) {
  const first = source.indexOf(start)
  if (first < 0 || source.indexOf(start, first + start.length) >= 0 || !source.slice(first).trimEnd().endsWith('}')) {
    throw new Error('Pinned Mailflare branding patch tail is not unique: ' + label)
  }
  return source.slice(0, first) + replacement + String.fromCharCode(10)
}

export function applyHelloAdaBrandingPatch(sources, basePath) {
  if (basePath !== '/mail') throw new Error('HelloAda branding requires the registered /mail base path')
  const iconPath = basePath + '/helloada-logo.svg'
  const newline = String.fromCharCode(10)

  let layout = replaceExactlyOnce(
    sources.layout,
    ['title: "Mailflare",', '	description: "Multi-tenant email on Cloudflare",'].join(newline),
    ['title: "HelloAda",', '	description: "HelloAda business inbox, contacts and booking calendar",'].join(newline),
    'document title and description',
  )
  layout = replaceExactlyOnce(layout, 'title: "Mailflare",', 'title: "HelloAda",', 'Apple web app title')
  layout = replaceExactlyOnce(
    layout,
    'icons: { icon: "/api/branding/icon", apple: "/icon-192.png" },',
    'icons: { icon: "' + iconPath + '", apple: "' + iconPath + '" },',
    'browser and Apple icons',
  )
  layout = replaceExactlyOnce(
    layout,
    '<link rel="icon" href="/api/branding/icon"></link>',
    '<link rel="icon" href="' + iconPath + '" type="image/svg+xml"></link>',
    'head favicon',
  )

  let manifest = replaceExactlyOnce(sources.manifest, 'name: "Mailflare",', 'name: "HelloAda",', 'manifest name')
  manifest = replaceExactlyOnce(manifest, 'short_name: "Mailflare",', 'short_name: "HelloAda",', 'manifest short name')
  manifest = replaceExactlyOnce(manifest, 'description: "Email, anywhere.",', 'description: "HelloAda business inbox, contacts and booking calendar",', 'manifest description')
  manifest = replaceExactlyOnce(manifest, 'start_url: "/inbox",', 'start_url: "' + basePath + '/inbox",', 'manifest start URL')
  manifest = replaceExactlyOnce(
    manifest,
    ['icons: [', '			{ src: "/icon-192.png", sizes: "192x192", type: "image/png" },', '			{ src: "/icon-512.png", sizes: "512x512", type: "image/png" },', '		],'].join(newline),
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
  brandingService = replaceExactlyOnce(brandingService, 'import { eq } from "drizzle-orm";', '', 'branding database import')
  brandingService = replaceExactlyOnce(brandingService, 'import { getDb } from "@/db";', '', 'branding database accessor')
  brandingService = replaceExactlyOnce(brandingService, 'import { appSettings } from "@/db/schema";', '', 'branding settings schema')
  brandingService = replaceExactlyOnce(brandingService, 'import { getLicenseEntitlements } from "@/lib/licenses/service";', '', 'branding entitlement import')
  brandingService = replaceExactlyOnce(
    brandingService,
    ['export const APP_SETTINGS_ID = "default";', 'export const DEFAULT_APP_NAME = "Mailflare";', 'export const BRANDING_ICON_KEY = "branding/app-icon";'].join(newline),
    'export const DEFAULT_APP_NAME = "HelloAda";',
    'fixed platform brand',
  )
  brandingService = replaceSection(
    brandingService,
    'export async function getBranding(env: CloudflareEnv): Promise<Branding> {',
    'export async function updateBranding(',
    'export async function getBranding(_env: CloudflareEnv): Promise<Branding> {' + newline
      + '	return { appName: DEFAULT_APP_NAME, hasCustomIcon: false, canCustomizeBranding: false }' + newline
      + '}',
    'fixed branding read',
  )
  brandingService = replaceTail(
    brandingService,
    'export async function updateBranding(',
    'export async function updateBranding(_env: CloudflareEnv, _input: { appName: string; icon?: File | null }): Promise<Branding> {' + newline
      + '	throw new Error("HelloAda branding is fixed for this workspace")' + newline
      + '}',
    'disabled tenant branding mutation',
  )

  let sidebarFooter = replaceExactlyOnce(sources.sidebarFooter, 'import packageJson from "../../package.json";', '', 'vendor version import')
  sidebarFooter = replaceLine(
    sidebarFooter,
    'href={' + String.fromCharCode(96) + 'https://mailflare.co/',
    '          href="https://helloada.app"',
    'vendor footer link',
  )
  sidebarFooter = replaceExactlyOnce(sidebarFooter, 'Mailflare v{packageJson.version}', 'HelloAda', 'vendor footer label')

  if (!sources.brandingIconRoute.includes('https://mailflare.local/icon-96.png')
      || !sources.brandingIconRoute.includes('export async function GET(request: Request)')) {
    throw new Error('Pinned Mailflare branding patch no longer recognizes the default icon route')
  }
  const brandingIconRoute = 'import { getEnvAsync } from "@/lib/cloudflare";' + newline + newline
    + 'export const dynamic = "force-dynamic";' + newline + 'export const revalidate = 0;' + newline + newline
    + 'export async function GET() {' + newline
    + '	const env = await getEnvAsync();' + newline
    + '	return env.ASSETS.fetch("https://mailflare.local' + iconPath + '");' + newline
    + '}' + newline

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
