const replaceExactlyOnce = (source, before, after, filename) => {
  const index = source.indexOf(before)
  if (index < 0 || source.indexOf(before, index + before.length) !== -1) {
    throw new Error("Pinned Mailflare booking UI patch no longer applies exactly once: " + filename)
  }
  return source.slice(0, index) + after + source.slice(index + before.length)
}

const replaceFunctionTail = (source, start, end, replacement, filename) => {
  const from = source.indexOf(start)
  const to = source.indexOf(end, from + start.length)
  if (from < 0 || to < 0 || source.indexOf(start, from + start.length) !== -1) {
    throw new Error("Pinned Mailflare booking UI patch no longer applies exactly once: " + filename)
  }
  return source.slice(0, from) + replacement + source.slice(to)
}

const patchedBookFunction = [
  'async function book(website: string) {',
  '\tif (!selectedSlot) return;',
  '\tif (!consent || !turnstileToken || !turnstileSiteKey) { setError(t("public.bookingSecurityRequired")); return; }',
  '\tconst payload = { startsAt: selectedSlot.startsAt, name: name.trim(), email: email.trim().toLowerCase(), guestEmails, notes: notes.trim(), consent: true as const };',
  '\tconst fingerprint = JSON.stringify(payload);',
  '\tconst previous = bookingRequestRef.current;',
  '\tconst requestId = previous?.fingerprint === fingerprint ? previous.requestId : crypto.randomUUID();',
  '\tbookingRequestRef.current = { fingerprint, requestId };',
  '\tsetSubmitting(true);',
  '\tsetError("");',
  '\ttry {',
  '\t\tawait submitPublicBooking(endpoint, { ...payload, requestId, turnstileToken, website });',
  '\t\tbookingRequestRef.current = null;',
  '\t\tsetDone(true);',
  '\t} catch (cause) {',
  '\t\tsetError(cause instanceof Error ? cause.message : t("public.bookFailed"));',
  '\t} finally {',
  '\t\tsetSubmitting(false);',
  '\t\tsetTurnstileToken("");',
  '\t\tsetTurnstileReset((value) => value + 1);',
  '\t}',
  '}',
].join("\n")

export function applyBookingUiPatch(sources) {
  let turnstile = replaceExactlyOnce(
    sources.turnstile,
    [
      'export function TurnstileField({',
      '\tname = "turnstileToken",',
      '\tresetSignal,',
      '}: {',
      '\tname?: string;',
      '\tresetSignal?: number;',
      '}) {',
      '\tconst containerRef = useRef<HTMLDivElement | null>(null);',
      '\tconst widgetId = useRef<string | undefined>(undefined);',
      '\tconst [token, setToken] = useState("");',
    ].join("\n"),
    [
      'export function TurnstileField({',
      '\tname = "turnstileToken",',
      '\tresetSignal,',
      '\tsiteKey,',
      '\tonTokenChange,',
      '}: {',
      '\tname?: string;',
      '\tresetSignal?: number;',
      '\tsiteKey?: string;',
      '\tonTokenChange?: (token: string) => void;',
      '}) {',
      '\tconst configuredSiteKey = siteKey === undefined ? TURNSTILE_SITE_KEY : siteKey;',
      '\tconst containerRef = useRef<HTMLDivElement | null>(null);',
      '\tconst widgetId = useRef<string | undefined>(undefined);',
      '\tconst [token, setToken] = useState("");',
    ].join("\n"),
    "TurnstileField props",
  )
  turnstile = replaceExactlyOnce(turnstile, 'if (!TURNSTILE_SITE_KEY || !containerRef.current) return;', 'if (!configuredSiteKey || !containerRef.current) return;', "TurnstileField site key")
  turnstile = replaceExactlyOnce(turnstile, 'sitekey: TURNSTILE_SITE_KEY,', 'sitekey: configuredSiteKey,', "Turnstile widget site key")
  turnstile = replaceExactlyOnce(
    turnstile,
    [
      '\t\t\t\tcallback: setToken,',
      '\t\t\t\t"expired-callback": () => setToken(""),',
      '\t\t\t\t"error-callback": () => setToken(""),',
    ].join("\n"),
    [
      '\t\t\t\tcallback: (nextToken) => { setToken(nextToken); onTokenChange?.(nextToken); },',
      '\t\t\t\t"expired-callback": () => { setToken(""); onTokenChange?.(""); },',
      '\t\t\t\t"error-callback": () => { setToken(""); onTokenChange?.(""); },',
    ].join("\n"),
    "Turnstile token callbacks",
  )
  turnstile = replaceExactlyOnce(turnstile, '\t}, []);', '\t}, [configuredSiteKey, onTokenChange]);', "Turnstile widget lifecycle")
  turnstile = replaceExactlyOnce(
    turnstile,
    '\t\tsetToken("");\n\t}, [resetSignal]);',
    '\t\tsetToken("");\n\t\tonTokenChange?.("");\n\t}, [resetSignal, onTokenChange]);',
    "Turnstile reset notification",
  )
  turnstile = replaceExactlyOnce(turnstile, 'if (!TURNSTILE_SITE_KEY) return null;', 'if (!configuredSiteKey) return null;', "Turnstile enabled state")

  let page = replaceExactlyOnce(
    sources.page,
    'import { useEffect, useMemo, useState } from "react";',
    'import { useEffect, useMemo, useRef, useState } from "react";',
    "booking page React imports",
  )
  page = replaceExactlyOnce(
    page,
    'import { LanguageSelector } from "@/components/language-selector";',
    'import { LanguageSelector } from "@/components/language-selector";\nimport { TurnstileField } from "@/components/auth/turnstile";',
    "booking page Turnstile import",
  )
  page = replaceExactlyOnce(
    page,
    '\tconst [error, setError] = useState("");',
    [
      '\tconst [error, setError] = useState("");',
      '\tconst [turnstileSiteKey, setTurnstileSiteKey] = useState("");',
      '\tconst [turnstileToken, setTurnstileToken] = useState("");',
      '\tconst [turnstileReset, setTurnstileReset] = useState(0);',
      '\tconst [consent, setConsent] = useState(false);',
      '\tconst bookingRequestRef = useRef<{ fingerprint: string; requestId: string } | null>(null);',
    ].join("\n"),
    "booking page security state",
  )
  page = replaceExactlyOnce(
    page,
    'return response.json() as Promise<{ event: PublicBookingEvent; hostName: string; slots: BookingSlot[] }>;',
    'return response.json() as Promise<{ event: PublicBookingEvent; hostName: string; slots: BookingSlot[]; turnstileSiteKey?: string }>;',
    "booking page API response type",
  )
  page = replaceExactlyOnce(
    page,
    '\t\t\tsetEvent(data.event);',
    '\t\t\tif (!data.turnstileSiteKey) throw new Error(t("public.securityUnavailable"));\n\t\t\tsetTurnstileSiteKey(data.turnstileSiteKey);\n\t\t\tsetEvent(data.event);',
    "booking page security configuration",
  )
  page = replaceFunctionTail(
    page,
    'async function book() {',
    '\n\n\treturn <main',
    patchedBookFunction + '\n',
    "booking page submission handler",
  )
  page = replaceExactlyOnce(
    page,
    '<form onSubmit={(formEvent) => { formEvent.preventDefault(); void book(); }} className="page-transition-enter min-h-0 space-y-6 overflow-y-auto p-7 max-sm:p-5 sm:p-10">',
    '<form onSubmit={(formEvent) => { formEvent.preventDefault(); void book(String(new FormData(formEvent.currentTarget).get("website") || "")); }} className="page-transition-enter min-h-0 space-y-6 overflow-y-auto p-7 max-sm:p-5 sm:p-10">',
    "booking page form submit",
  )
  page = replaceExactlyOnce(
    page,
    '<h2 className="text-2xl font-medium">{t("public.enterDetails")}</h2>',
    '<h2 className="text-2xl font-medium">{t("public.enterDetails")}</h2>\n\t\t\t\t\t\t\t<div className="hidden" aria-hidden="true"><label>Website<input name="website" tabIndex={-1} autoComplete="off" /></label></div>',
    "booking page honeypot",
  )
  page = replaceExactlyOnce(
    page,
    '{error && <p role="alert" className="text-sm text-red-600">{error}</p>}',
    [
      '<label className="flex items-start gap-2 text-sm text-neutral-600"><input type="checkbox" required checked={consent} onChange={(input) => setConsent(input.target.checked)} className="mt-1" /><span>{t("public.bookingConsent")}</span></label>',
      '<TurnstileField siteKey={turnstileSiteKey} resetSignal={turnstileReset} onTokenChange={setTurnstileToken} />',
      '{error && <p role="alert" className="text-sm text-red-600">{error}</p>}',
    ].join("\n\t\t\t\t\t\t\t"),
    "booking page consent and security",
  )
  page = replaceExactlyOnce(
    page,
    'disabled={submitting || !name.trim() || !email.trim()}',
    'disabled={submitting || !name.trim() || !email.trim() || !turnstileSiteKey || !turnstileToken || !consent}',
    "booking page secure submit condition",
  )

  const bookingUtils = replaceExactlyOnce(
    sources.bookingUtils,
    'export async function submitPublicBooking(endpoint: string, startsAt: string, name: string, email: string, guestEmails: string, notes: string): Promise<void> {\n\tconst response = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ startsAt, name, email, guestEmails, notes }) });',
    [
      'export async function submitPublicBooking(endpoint: string, booking: {',
      '\tstartsAt: string;',
      '\tname: string;',
      '\temail: string;',
      '\tguestEmails: string;',
      '\tnotes: string;',
      '\tconsent: true;',
      '\trequestId: string;',
      '\tturnstileToken: string;',
      '\twebsite: string;',
      '}): Promise<void> {',
      '\tconst response = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(booking) });',
    ].join("\n"),
    "public booking client payload",
  )
  const i18n = replaceExactlyOnce(
    sources.i18n,
    '\t"public.notes": "Please share anything that will help prepare for our meeting.",',
    [
      '\t"public.notes": "Please share anything that will help prepare for our meeting.",',
      '\t"public.bookingConsent": "I agree that the business may use these details to manage this booking.",',
      '\t"public.bookingSecurityRequired": "Complete the security check and confirm the privacy notice to book.",',
      '\t"public.securityUnavailable": "Online booking security is not configured for this meeting.",',
    ].join("\n"),
    "public booking security copy",
  )
  return { turnstile, page, bookingUtils, i18n }
}
