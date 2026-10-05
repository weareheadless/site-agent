'use client'

import Script from 'next/script'
import { useRef, useState } from 'react'
import type { FormEvent } from 'react'

type FormField = {
  key: string
  label: string
  type: 'text' | 'email' | 'phone' | 'textarea' | 'select' | 'consent'
  placeholder?: string
  required?: boolean
  maxLength?: number
  choices?: Array<{ key: string; label: string }>
}

type FormDocument = {
  slug: string
  title: string
  intro?: string
  submitLabel: string
  successMessage: string
  fields: FormField[]
}

declare global {
  interface Window {
    turnstile?: { render: (element: HTMLElement, options: Record<string, unknown>) => string; reset: (widgetId?: string) => void }
  }
}

export default function ContactForm({ form, siteKey }: { form: FormDocument; siteKey: string }) {
  const [state, setState] = useState<'ready' | 'sending' | 'sent' | 'error'>('ready')
  const [error, setError] = useState('')
  const turnstileRef = useRef<HTMLDivElement>(null)
  const widgetIdRef = useRef<string | undefined>(undefined)
  const requestRef = useRef<{ fingerprint: string; requestId: string } | undefined>(undefined)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (state === 'sending' || state === 'sent') return
    const element = event.currentTarget
    const data = new FormData(element)
    const token = String(data.get('cf-turnstile-response') || '')
    if (!token) { setState('error'); setError('Please complete the security check.'); return }
    const answers = Object.fromEntries(form.fields.map((field) => [field.key, field.type === 'consent' ? data.get(field.key) === 'on' : String(data.get(field.key) || '')]))
    const fingerprint = JSON.stringify(answers)
    if (requestRef.current?.fingerprint !== fingerprint) {
      requestRef.current = { fingerprint, requestId: globalThis.crypto.randomUUID() }
    }
    setState('sending')
    setError('')
    try {
      const response = await fetch(`/api/helloada/forms/${encodeURIComponent(form.slug)}`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ answers, requestId: requestRef.current.requestId, turnstileToken: token, website: String(data.get('website') || '') }),
      })
      const result = await response.json().catch(() => ({})) as { error?: string }
      if (!response.ok) throw new Error(result.error || 'The message could not be sent. Please try again.')
      setState('sent')
      requestRef.current = undefined
      element.reset()
      window.turnstile?.reset(widgetIdRef.current)
    } catch (cause) {
      setState('error')
      setError(cause instanceof Error ? cause.message : 'The message could not be sent. Please try again.')
      window.turnstile?.reset(widgetIdRef.current)
    }
  }

  return <form className="helloada-contact-form" onSubmit={submit}>
    {form.intro ? <p>{form.intro}</p> : null}
    {form.fields.map((field) => <label className={`helloada-form-field${field.type === 'consent' ? ' is-consent' : ''}`} key={field.key}>
      {field.type === 'consent' ? <>
        <input name={field.key} type="checkbox" required={field.required} />
        <span>{field.label}</span>
      </> : <>
        <span>{field.label}{field.required ? <span aria-hidden="true"> *</span> : null}</span>
        {field.type === 'textarea' ? <textarea name={field.key} maxLength={field.maxLength || 4000} placeholder={field.placeholder} required={field.required} rows={5} />
          : field.type === 'select' ? <select name={field.key} required={field.required} defaultValue=""><option value="" disabled>Select…</option>{(field.choices || []).map((choice) => <option key={choice.key} value={choice.key}>{choice.label}</option>)}</select>
            : <input name={field.key} type={field.type === 'phone' ? 'tel' : field.type} maxLength={field.maxLength || 500} placeholder={field.placeholder} required={field.required} autoComplete={field.type === 'email' ? 'email' : field.type === 'phone' ? 'tel' : undefined} />}
      </>}
    </label>)}
    <label className="helloada-form-honeypot" aria-hidden="true" tabIndex={-1}>
      <span>Website</span><input name="website" autoComplete="off" tabIndex={-1} />
    </label>
    <Script id="helloada-turnstile" src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit" strategy="afterInteractive" onLoad={() => {
      if (turnstileRef.current && window.turnstile && !widgetIdRef.current) widgetIdRef.current = window.turnstile.render(turnstileRef.current, { sitekey: siteKey, theme: 'auto' })
    }} />
    <div className="helloada-turnstile" ref={turnstileRef} />
    {state === 'sent' ? <p className="helloada-form-success" role="status">{form.successMessage}</p> : null}
    {error ? <p className="helloada-form-error" role="alert">{error}</p> : null}
    {state !== 'sent' ? <button type="submit" disabled={state === 'sending'}>{state === 'sending' ? 'Sending…' : form.submitLabel}</button> : null}
  </form>
}
