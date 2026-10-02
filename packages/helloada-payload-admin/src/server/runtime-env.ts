import { getCloudflareContext } from "@opennextjs/cloudflare";

/** Server-only, request-time binding lookup. Never export from the UI barrel. */
export function helloAdaRuntime() {
  let bindings: Record<string, unknown> | undefined;
  try {
    bindings = getCloudflareContext().env as unknown as Record<string, unknown>;
  } catch {
    /* Node/local tests */
  }
  const value = (name: string) =>
    String(bindings ? bindings[name] || "" : process.env[name] || "").trim();
  const url = value("SITE_AGENT_URL").replace(/\/$/, "");
  const token = value("HELLOADA_SITE_AGENT_TOKEN");
  return {
    url,
    token,
    configured: Boolean(url && token),
    source: bindings ? "cloudflare" : "process",
  };
}

export function helloAdaRuntimeStatus() {
  const runtime = helloAdaRuntime();
  return {
    configured: runtime.configured,
    urlConfigured: Boolean(runtime.url),
    tokenConfigured: Boolean(runtime.token),
    source: runtime.source,
  };
}

/** Owner-authenticated diagnostics: never return URL/token values. */
export function helloAdaConnection(
  expectedTenant: string,
  upstream?: { body: unknown; status: number },
) {
  const runtime = helloAdaRuntimeStatus();
  const body = upstream?.body as
    | { tenant?: string; ready?: boolean; connected?: boolean }
    | undefined;
  const matches = body?.tenant === expectedTenant;
  const connected = Boolean(
    runtime.configured &&
      upstream?.status === 200 &&
      matches &&
      body?.connected === true &&
      body?.ready === true,
  );
  const error = !runtime.configured
    ? "runtime_unconfigured"
    : !upstream
      ? "backend_unreachable"
      : upstream.status !== 200
        ? "backend_rejected"
        : !matches
          ? "tenant_mismatch"
          : body?.ready !== true
            ? "ai_unconfigured"
            : body?.connected !== true ? "backend_invalid" : undefined;
  return {
    status: connected ? 200 : 503,
    body: {
      ...runtime,
      connected,
      tenant: expectedTenant,
      ready: connected,
      error,
      upstreamStatus: upstream?.status,
    },
  };
}
