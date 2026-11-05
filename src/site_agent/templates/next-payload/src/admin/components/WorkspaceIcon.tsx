import type { CSSProperties } from 'react'

type IconName = 'arrow' | 'chevron' | 'close' | 'desktop' | 'mobile' | 'tablet' | 'plus' | 'settings' | 'check' | 'external' | 'refresh'

const paths: Record<IconName, string> = {
  refresh: 'M20 7v5h-5M4 17v-5h5M5 8a8 8 0 0 1 13-3l2 3M19 16A8 8 0 0 1 6 19l-2-3',
  arrow: 'M5 12h14m-6-6 6 6-6 6',
  chevron: 'm8 10 4 4 4-4',
  close: 'm6 6 12 12M6 18 18 6',
  desktop: 'M4 4h16v12H4zM8 20h8m-4-4v4',
  mobile: 'M7 2h10v20H7zM11 18h2',
  tablet: 'M5 2h14v20H5zM11 18h2',
  plus: 'M12 5v14M5 12h14',
  settings: 'M4 7h16M4 17h16M8 4v6m8 4v6',
  check: 'm5 12 4 4 10-10',
  external: 'M14 4h6v6m0-6L10 14M10 4H4v16h16v-6',
}

export function WorkspaceIcon({ name, size = 18, style }: { name: IconName; size?: number; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}><path d={paths[name]} /></svg>
}
