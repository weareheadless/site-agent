export function GET() {
  return Response.json({
    ok: true,
    service: 'helloada-site',
    tenant: process.env.HELLOADA_TENANT_ID || null,
    templateSchema: Number(process.env.HELLOADA_TEMPLATE_SCHEMA || 2),
    payloadAdmin: process.env.HELLOADA_PAYLOAD_ADMIN_VERSION || '0.1.2',
    workspaceApi: process.env.HELLOADA_WORKSPACE_API_VERSION || 'v1',
    siteAgent: process.env.HELLOADA_SITE_AGENT_VERSION || null,
    compatible: true,
  })
}
