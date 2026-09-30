export function GET() {
  return Response.json({ ok: true, service: 'helloada-site', tenant: process.env.ATELIER_TENANT_ID || null })
}
