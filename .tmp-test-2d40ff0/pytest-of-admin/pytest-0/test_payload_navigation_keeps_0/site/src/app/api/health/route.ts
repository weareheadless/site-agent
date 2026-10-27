export const dynamic = 'force-dynamic'

export function GET() {
  return Response.json({
    ok: true,
    service: 'helloada-site',
    tenant: process.env.HELLOADA_TENANT_ID || null,
    templateSchema: Number(process.env.HELLOADA_TEMPLATE_SCHEMA || 4),
    payloadAdmin: process.env.HELLOADA_PAYLOAD_ADMIN_VERSION || null,
    payloadCore: process.env.HELLOADA_PAYLOAD_CORE_VERSION || null,
    contentContract: process.env.HELLOADA_CONTENT_CONTRACT_VERSION || null,
    workspaceApi: process.env.HELLOADA_WORKSPACE_API_VERSION || null,
    siteAgent: process.env.HELLOADA_SITE_AGENT_VERSION || null,
    releaseSha: process.env.HELLOADA_RELEASE_SHA || null,
  }, { headers: { 'Cache-Control': 'no-store' } })
}
