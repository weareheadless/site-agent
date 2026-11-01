import Hero from './hero'
import type { SectionProps } from './registry'

function GalleryImage({ image, marker, monochrome }: {
  image: { src: string; alt: string }; marker?: string; monochrome: boolean
}) {
  return <img src={image.src} alt={image.alt} data-helloada-field={marker}
    className={`aspect-[4/3] w-full object-cover ${monochrome ? 'grayscale' : ''}`} loading="lazy" decoding="async" />
}

/** Supporting sections share the direction grammar, not tenant-specific copy. */
export default function Supporting({ content, direction, bindings = {}, signature }: SectionProps) {
  const { additionalImages, ...primaryContent } = content
  return (
    <>
      <Hero content={primaryContent} direction={direction} bindings={bindings} signature={signature} headingLevel="h2" />
      {additionalImages?.length ? (
        <div className="grid grid-cols-1 gap-6 bg-paper px-6 pb-16 sm:grid-cols-2 sm:px-10 md:px-14">
          {additionalImages.map((image, index) => (
            <GalleryImage key={bindings.additionalImages?.[index] ?? image.src} image={image}
              marker={bindings.additionalImages?.[index]} monochrome={direction?.treatment === 'monochrome'} />
          ))}
        </div>
      ) : null}
    </>
  )
}
