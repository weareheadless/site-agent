import type { ReactNode } from 'react'

/**
 * A hero section with art direction as data.
 *
 * The component owns structure only: grid, responsive behaviour, crop and the
 * rules that carry the page. It deliberately has no fixed look. Alignment,
 * rule usage, image treatment and display scale are direction, and direction
 * is the designer's decision, not the component's.
 */

export type HeroAlignment = 'split-left' | 'split-right' | 'centred' | 'overlap' | 'reversed'

export type HeroDirection = {
  align?: HeroAlignment
  /** Hairline rules carry the structure instead of boxes or shadows. */
  rules?: boolean
  /** Monochrome converts the photograph; colour leaves it as supplied. */
  treatment?: 'colour' | 'monochrome'
  /** Editorial runs the display face large; compact is quieter. */
  scale?: 'editorial' | 'compact'
}

export type HeroContent = {
  eyebrow?: string
  headline: string
  /** Rendered in italic inside the headline, for the phrase that breaks rhythm. */
  emphasis?: string
  body?: string
  /** Further approved copy; kept visible instead of being dropped. */
  supporting?: string[]
  action?: { label: string; href: string }
  image?: { src: string; alt: string }
}

/**
 * The owner's editable binding for each rendered part, as the exact
 * `data-helloada-field` marker. A composed page stays editable in the
 * workspace instead of becoming a picture of Payload data.
 */
export type SectionMarkers = {
  eyebrow?: string
  headline?: string
  body?: string
  supporting?: (string | undefined)[]
  action?: string
  image?: string
}

type HeroProps = {
  content: HeroContent
  direction?: HeroDirection
  bindings?: SectionMarkers
  /** One deliberate gesture, supplied by the designer. Rendered as-is. */
  signature?: ReactNode
}

const displaySize: Record<NonNullable<HeroDirection['scale']>, string> = {
  editorial: 'text-[clamp(2.6rem,7vw,5.4rem)]',
  compact: 'text-[clamp(2rem,4.2vw,3.4rem)]',
}

const imageTreatment: Record<NonNullable<HeroDirection['treatment']>, string> = {
  colour: '',
  monochrome: 'grayscale',
}

const sectionPad = 'px-6 py-16 sm:px-10 md:px-14 md:py-20 lg:py-24'

function Eyebrow({ children, marker }: { children: ReactNode; marker?: string }) {
  return (
    <p className="text-[0.66rem] uppercase tracking-[0.28em] text-muted" data-helloada-field={marker}>{children}</p>
  )
}

function Headline({ content, scale, marker }: {
  content: HeroContent
  scale: NonNullable<HeroDirection['scale']>
  marker?: string
}) {
  return (
    <h1 className={`font-display leading-[0.95] tracking-[-0.02em] text-ink ${displaySize[scale]}`} data-helloada-field={marker}>
      {content.headline}
      {content.emphasis ? (
        <>
          {' '}
          <em className="italic">{content.emphasis}</em>
        </>
      ) : null}
    </h1>
  )
}

function Action({ action, marker }: { action?: HeroContent['action']; marker?: string }) {
  if (!action) return null
  return (
    <a
      href={action.href}
      className="inline-block border-b border-ink pb-1 text-[0.68rem] uppercase tracking-[0.22em] text-ink"
      data-helloada-field={marker}
    >
      {action.label}
    </a>
  )
}

function Body({ children, supporting = [], marker, supportingMarkers = [] }: {
  children?: string
  supporting?: string[]
  marker?: string
  supportingMarkers?: (string | undefined)[]
}) {
  if (!children && !supporting.length) return null
  return (
    <div className="flex max-w-[34ch] flex-col gap-3">
      {children ? <p className="text-[0.92rem] leading-[1.7] text-body" data-helloada-field={marker}>{children}</p> : null}
      {supporting.map((paragraph, index) => (
        <p key={index} className="text-[0.92rem] leading-[1.7] text-body" data-helloada-field={supportingMarkers[index]}>
          {paragraph}
        </p>
      ))}
    </div>
  )
}

function Rule({ tone = 'ink' }: { tone?: 'ink' | 'paper' }) {
  return <div className={`h-px w-full ${tone === 'paper' ? 'bg-rule-paper' : 'bg-rule'}`} />
}

function Figure({ image, treatment, marker, className = '' }: {
  image?: HeroContent['image']
  treatment: NonNullable<HeroDirection['treatment']>
  marker?: string
  className?: string
}) {
  if (!image) return null
  return (
    <img
      src={image.src}
      alt={image.alt}
      data-helloada-field={marker}
      className={`h-full w-full object-cover ${imageTreatment[treatment]} ${className}`}
      loading="eager"
      decoding="async"
    />
  )
}

export function Hero({ content, direction = {}, bindings = {}, signature }: HeroProps) {
  const align = direction.align ?? 'split-left'
  const rules = direction.rules ?? true
  const treatment = direction.treatment ?? 'colour'
  const scale = direction.scale ?? 'editorial'

  if (align === 'reversed') {
    return (
      <section className="relative overflow-hidden bg-ink text-paper">
        <div className="absolute inset-0">
          <Figure image={content.image} treatment="monochrome" marker={bindings.image} />
          <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(18,17,16,.55)_0%,rgba(18,17,16,.15)_42%,rgba(18,17,16,.74)_100%)]" />
        </div>
        <div className={`relative flex min-h-[26rem] flex-col justify-between ${sectionPad}`}>
          <div className="flex items-baseline justify-between gap-6">
            {content.eyebrow ? <Eyebrow marker={bindings.eyebrow}>{content.eyebrow}</Eyebrow> : <span />}
            {signature}
          </div>
          <div className="grid grid-cols-1 items-end gap-8 md:grid-cols-12">
            <div className="md:col-span-8">
              <Headline content={content} scale={scale} marker={bindings.headline} />
            </div>
            <div className="md:col-span-4">
              {rules ? <Rule tone="paper" /> : null}
              <div className="mt-5 flex flex-col gap-4">
                <Body supporting={content.supporting} marker={bindings.body} supportingMarkers={bindings.supporting}>{content.body}</Body>
                <Action action={content.action} marker={bindings.action} />
              </div>
            </div>
          </div>
        </div>
      </section>
    )
  }

  if (align === 'centred') {
    return (
      <section className={`bg-paper ${sectionPad}`}>
        <div className="mx-auto max-w-3xl text-center">
          {content.eyebrow ? <Eyebrow marker={bindings.eyebrow}>{content.eyebrow}</Eyebrow> : null}
          <div className="mt-6">
            <Headline content={content} scale={scale} marker={bindings.headline} />
          </div>
          <div className="mx-auto mt-6 flex max-w-xl flex-col items-center gap-4">
            <Body supporting={content.supporting} marker={bindings.body} supportingMarkers={bindings.supporting}>{content.body}</Body>
            <Action action={content.action} marker={bindings.action} />
          </div>
        </div>
        {content.image ? (
          <div className="mx-auto mt-12 h-[clamp(14rem,38vw,24rem)] w-full max-w-4xl overflow-hidden">
            <Figure image={content.image} treatment={treatment} marker={bindings.image} />
          </div>
        ) : null}
        {signature ? <div className="mx-auto mt-10 flex justify-center">{signature}</div> : null}
      </section>
    )
  }

  const copyFirst = align !== 'split-right'
  const overlap = align === 'overlap'
  return (
    <section className={`bg-paper ${sectionPad}`}>
      <div className="mx-auto grid max-w-6xl grid-cols-1 items-center gap-10 md:grid-cols-12">
        <div className={`md:col-span-6 ${copyFirst ? 'md:order-1' : 'md:order-2'} ${overlap ? 'md:relative md:z-10' : ''}`}>
          {content.eyebrow ? <Eyebrow marker={bindings.eyebrow}>{content.eyebrow}</Eyebrow> : null}
          <div className="mt-5">
            <Headline content={content} scale={scale} marker={bindings.headline} />
          </div>
          {rules ? <div className="mt-7 max-w-[6rem]"><Rule /></div> : null}
          <div className="mt-6 flex flex-col gap-5">
            <Body supporting={content.supporting} marker={bindings.body} supportingMarkers={bindings.supporting}>{content.body}</Body>
            <Action action={content.action} marker={bindings.action} />
          </div>
          {signature ? <div className="mt-8">{signature}</div> : null}
        </div>
        <div className={`md:col-span-6 ${copyFirst ? 'md:order-2' : 'md:order-1'} ${overlap ? 'md:-ml-12' : ''}`}>
          <div className="h-[clamp(16rem,42vw,30rem)] overflow-hidden">
            <Figure image={content.image} treatment={treatment} marker={bindings.image} />
          </div>
        </div>
      </div>
    </section>
  )
}

export default Hero
