'use client'

import { useEffect } from 'react'

const HEIGHT_MESSAGE = 'helloada:booking-frame-height'

/**
 * An embedded booking frame reports its own height so the host page can size
 * the frame instead of clipping the form or leaving a scrollbar inside it.
 */
export default function FrameHeight() {
  useEffect(() => {
    if (window.parent === window) return
    let reported = 0
    const report = () => {
      const height = Math.ceil(document.documentElement.getBoundingClientRect().height)
      if (!height || height === reported) return
      reported = height
      window.parent.postMessage({ type: HEIGHT_MESSAGE, height }, window.location.origin)
    }
    report()
    const observer = new ResizeObserver(report)
    observer.observe(document.documentElement)
    if (document.body) observer.observe(document.body)
    window.addEventListener('load', report)
    return () => {
      observer.disconnect()
      window.removeEventListener('load', report)
    }
  }, [])
  return null
}
