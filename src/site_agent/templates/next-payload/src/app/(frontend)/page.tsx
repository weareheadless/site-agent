import Link from 'next/link'

export default function HomePage() {
  const name = process.env.HELLOADA_SITE_NAME || 'Your new website'
  return (
    <main style={{ maxWidth: 720, margin: '0 auto', padding: '12vh 24px', fontFamily: 'system-ui, sans-serif' }}>
      <p style={{ color: '#666', letterSpacing: '0.08em', textTransform: 'uppercase' }}>HelloAda workspace</p>
      <h1>{name}</h1>
      <p>Your managed Payload website is ready for its first owner-approved page.</p>
      <Link href="/admin">Open the content studio</Link>
    </main>
  )
}
