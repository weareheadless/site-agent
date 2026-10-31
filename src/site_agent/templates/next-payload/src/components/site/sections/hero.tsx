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
  action?: { label: string; href: string }
  image?: { src: string; alt: string }
}

type HeroProps = {
  content: HeroContent
  direction?: HeroDirection
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

function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <p className="text-[0.66rem] uppercase tracking-[0.28em] text-muted">{children}</p>
  )
}

function Headline({ content, scale }: { content: HeroContent; scale: NonNullable<HeroDirection['scale']> }) {
  return (
    <h1 className={`font-display leading-[0.95] tracking-[-0.02em] text-ink ${displaySize[scale]}`}>
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

function Action({ action }: { action?: HeroContent['action'] }) {
  if (!action) return null
  return (
    <a
      href={action.href}
      className="inline-block border-b border-ink pb-1 text-[0.68rem] uppercase tracking-[0.22em] text-ink"
    >
      {action.label}
    </a>
  )
}

function Body({ children }: { children?: string }) {
  if (!children) return null
  return <p className="max-w-[34ch] text-[0.92rem] leading-[1.7] text-body">{children}</p>
}

function Rule({ tone = 'ink' }: { tone?: 'ink' | 'paper' }) {
  return <div className={`h-px w-full ${tone === 'paper' ? 'bg-rule-paper' : 'bg-rule'}`} />
}

function Figure({ image, treatment, className = '' }: {
  image?: HeroContent['image']
  treatment: NonNullable<HeroDirection['treatment']>
  className?: string
}) {
  if (!image) return null
  return (
    <img
      src={image.src}
      alt={image.alt}
      className={`h-full w-full object-cover ${imageTreatment[treatment]} ${className}`}
      loading="eager"
      decoding="async"
    />
  )
}

export function Hero({ content, direction = {}, signature }: HeroProps) {
  const align = direction.align ?? 'split-left'
  const rules = direction.rules ?? true
  const treatment = direction.treatment ?? 'colour'
  const scale = direction.scale ?? 'editorial'

  if (align === 'reversed') {
    return (
      <section className="relative overflow-hidden bg-ink text-paper">
        <div className="absolute inset-0">
          <Figure image={content.image} treatment="monochrome" />
          <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(18,17,16,.55)_0%,rgba(18,17,16,.15)_42%,rgba(18,17,16,.74)_100%)]" />
        </div>
        <div className={`relative flex min-h-[26rem] flex-col justify-between ${sectionPad}`}>
          <div className="flex items-baseline justify-between gap-6">
            {content.eyebrow ? <Eyebrow>{content.eyebrow}</Eyebrow> : <span />}
            {signature}
          </div>
          <div className="grid grid-cols-1 items-end gap-8 md:grid-cols-12">
            <div className="md:col-span-8">
              <Headline content={content} scale={scale} />
            </div>
            <div className="md:col-span-4">
              {rules ? <Rule tone="paper" /> : null}
              <div className="mt-5 flex flex-col gap-4">
                <Body>{content.body}</Body>
                <Action action={content.action} />
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
          {content.eyebrow ? <Eyebrow>{content.eyebrow}</Eyebrow> : null}
          <div className="mt-6">
            <Headline content={content} scale={scale} />
          </div>
          <div className="mx-auto mt-6 flex max-w-xl flex-col items-center gap-4">
            <Body>{content.body}</Body>
            <Action action={content.action} />
          </div>
        </div>
        {content.image ? (
          <div className="mx-auto mt-12 h-[clamp(14rem,38vw,24rem)] w-full max-w-4xl overflow-hidden">
            <Figure image={content.image} treatment={treatment} />
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
          {content.eyebrow ? <Eyebrow>{content.eyebrow}</Eyebrow> : null}
          <div className="mt-5">
            <Headline content={content} scale={scale} />
          </div>
          {rules ? <div className="mt-7 max-w-[6rem]"><Rule /></div> : null}
          <div className="mt-6 flex flex-col gap-5">
            <Body>{content.body}</Body>
            <Action action={content.action} />
          </div>
          {signature ? <div className="mt-8">{signature}</div> : null}
        </div>
        <div className={`md:col-span-6 ${copyFirst ? 'md:order-2' : 'md:order-1'} ${overlap ? 'md:-ml-12' : ''}`}>
          <div className="h-[clamp(16rem,42vw,30rem)] overflow-hidden">
            <Figure image={content.image} treatment={treatment} />
          </div>
        </div>
      </div>
    </section>
  )
}

export default Hero
