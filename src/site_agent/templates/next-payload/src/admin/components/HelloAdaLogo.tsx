import Link from 'next/link'

export function HelloAdaMark({ size = 42 }: { size?: number }) {
  return (
    // Exact geometry from helloada.app/public/helloada-mark.svg.
    <svg className="helloada-mark" width={size} height={size} viewBox="0 0 1024 1024" fill="none" role="img" aria-label="HelloAda">
      <rect width="1024" height="1024" rx="224" fill="#090706" />
      <ellipse cx="426" cy="522" rx="222" ry="236" stroke="#FF6B5E" strokeWidth="104" />
      <path d="M648 286V684" stroke="#FF6B5E" strokeWidth="104" strokeLinecap="round" />
      <rect x="596" y="650" width="148" height="148" rx="38" fill="#FFC857" />
    </svg>
  )
}

export function HelloAdaLogo() {
  return (
    <Link className="helloada-admin-logo" href="/admin" aria-label="HelloAda studio">
      <HelloAdaMark />
      <span>
        <strong>HelloAda</strong>
      </span>
    </Link>
  )
}

export function HelloAdaIcon() {
  return <span className="helloada-admin-icon"><HelloAdaMark size={30} /></span>
}
