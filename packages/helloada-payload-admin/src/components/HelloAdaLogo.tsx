import Link from 'next/link'

export function HelloAdaMark({ size = 42 }: { size?: number }) {
  return (
    <svg className="helloada-mark" width={size} height={size} viewBox="0 0 42 42" role="img" aria-label="HelloAda">
      <rect width="42" height="42" rx="13" fill="#191513" />
      <path d="M11 29.5c0-8.9 4.35-15.2 11.4-15.2 4.8 0 8.1 2.7 8.1 7.35V31h-5.05v-2.8c-1.4 1.95-3.25 2.95-5.8 2.95-3.15 0-5.2-1.55-5.2-4.15 0-2.95 2.65-4.55 7.35-4.55h3.65v-.95c0-1.9-1.22-3.02-3.4-3.02-3.12 0-4.78 2.38-5.05 6.25h-5.95v4.78Z" fill="#ff6b5e" />
      <path d="M25.55 24.95h4.9v3.5h-4.9z" fill="#ffc857" />
    </svg>
  )
}

export function HelloAdaLogo() {
  return (
    <Link className="helloada-admin-logo" href="/admin" aria-label="HelloAda studio">
      <HelloAdaMark />
      <span>
        <strong>helloada</strong>
        <small>.app / studio</small>
      </span>
    </Link>
  )
}

export function HelloAdaIcon() {
  return <span className="helloada-admin-icon"><HelloAdaMark size={30} /></span>
}
