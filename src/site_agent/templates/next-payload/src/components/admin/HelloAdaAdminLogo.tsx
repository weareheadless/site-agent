import React from 'react'

/**
 * HelloAda is the brand the owner sees from helloada.app through to their own
 * content workspace, so the tenant admin uses the same mark instead of
 * Payload's. Both graphics live in the platform-owned admin folder and are
 * referenced by `payload.config.ts`; the surrounding palette and type come
 * from `custom.scss`.
 */
const mark = '/brand/helloada-logo.svg'

export const HelloAdaAdminLogo: React.FC = () => (
  <span
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '10px',
      textDecoration: 'none',
      color: 'inherit',
    }}
  >
    <img src={mark} alt="" width={26} height={26} style={{ borderRadius: '7px', display: 'block' }} />
    <span
      style={{
        fontFamily: "'Avenir Next', 'Segoe UI Variable', ui-sans-serif, system-ui, sans-serif",
        fontSize: '16px',
        fontWeight: 600,
        letterSpacing: '-0.01em',
      }}
    >
      HelloAda
    </span>
  </span>
)

export const HelloAdaAdminIcon: React.FC = () => (
  <img src={mark} alt="HelloAda" width={24} height={24} style={{ borderRadius: '6px', display: 'block' }} />
)
