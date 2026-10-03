import { getCloudflareContext } from "@opennextjs/cloudflare";

/** One method/path contract for shared UI additions and thin tenant bridges. */
export function helloAdaWorkspacePath(path: string, method: string, search = ""): string | undefined {
  const suffix = path.replace(/^\/api\/(helloada|atelier)/, "") || "/";
  if (method === "GET" && ["/connection", "/growth", "/seo/analytics", "/seo/insights", "/seo/evidence"].includes(suffix)) return `/workspace${suffix}${search}`;
  if (method === "POST" && suffix === "/growth/check") return `/workspace/growth/check${search}`;
  if (suffix === "/ada" && method === "POST") return `/workspace/chat${search}`;
  if (suffix === "/ada" && method === "GET") {
    const jobId = new URLSearchParams(search).get("job_id");
    return jobId ? `/workspace/chat/jobs/${encodeURIComponent(jobId)}` : `/workspace/chat/status${search}`;
  }
  if (suffix === "/intake/confirm" && method === "POST") return `/workspace/chat/intake/confirm${search}`;
  if (suffix === "/design/start" && method === "POST") return `/workspace/chat/design/start${search}`;
  if (suffix === "/conversations" && ["GET", "POST"].includes(method)) return `/workspace/chat/conversations${search}`;
  const conversation = suffix.match(/^\/conversations\/([0-9]+)$/);
  if (conversation && ["GET", "DELETE"].includes(method)) return `/workspace/chat/conversations/${conversation[1]}${search}`;
  if (["/history", "/drafts"].includes(suffix) && method === "GET") return `/workspace${suffix}${search}`;
  const draft = suffix.match(/^\/drafts\/([0-9]+)\/(approve|discard)$/);
  if (draft && method === "POST") return `/workspace/drafts/${draft[1]}/${draft[2]}${search}`;
  const version = suffix.match(/^\/versions\/([0-9]+)\/restore$/);
  if (version && method === "POST") return `/workspace/versions/${version[1]}/restore${search}`;
  if (suffix === "/worktree/discard" && method === "POST") return `/workspace/worktree/discard${search}`;
  if (suffix === "/source/preview" && method === "POST") return `/workspace/source/preview${search}`;
  if (/^\/source\/preview\/[0-9]+(?:\/deploy|\/runtime(?:\/.*)?)?$/.test(suffix) && ["GET", "POST"].includes(method)) return `/workspace${suffix}${search}`;
  return undefined;
}

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
