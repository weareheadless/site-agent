import Hero from './hero'

/**
 * Section vocabulary.
 *
 * A page is an ordered list of sections. Each entry names a type here; the
 * component renders structure from the section's content and its direction
 * parameters. Adding a section means adding a component and a line here — it
 * does not change how any existing page renders.
 */
export const sectionComponents = {
  hero: Hero,
} as const

export type SectionType = keyof typeof sectionComponents

export function isSectionType(value: string): value is SectionType {
  return Object.hasOwn(sectionComponents, value)
}
