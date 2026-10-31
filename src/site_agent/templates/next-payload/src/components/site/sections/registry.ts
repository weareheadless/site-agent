import type { ReactNode } from 'react'
import Hero, { type HeroContent, type HeroDirection, type SectionMarkers } from './hero'

/**
 * Section vocabulary.
 *
 * A page is an ordered list of sections. Each entry names a type here; the
 * component renders structure from the section's content and its direction
 * parameters. Adding a section means adding a component and a line here — it
 * does not change how any existing page renders.
 */

export type SectionProps = {
  content: HeroContent
  direction?: HeroDirection
  bindings?: SectionMarkers
  signature?: ReactNode
}

export const sectionComponents: Record<string, (props: SectionProps) => ReactNode> = {
  hero: Hero,
}

export function isSectionType(value: string): boolean {
  return Object.hasOwn(sectionComponents, value)
}
