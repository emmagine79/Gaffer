import type { ReactNode } from 'react'
import './controls.css'

export function Segmented<T extends string | number>({
  value, options, onChange, label, size = 'md',
}: {
  value: T
  options: { value: T; label: ReactNode; title?: string }[]
  onChange: (value: T) => void
  label: string
  size?: 'sm' | 'md'
}) {
  return (
    <div className={`segmented segmented--${size}`} role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          title={o.title}
          className={o.value === value ? 'is-on' : ''}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (on: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} className={`toggle ${on ? 'is-on' : ''}`} onClick={() => onChange(!on)}>
      <span className="toggle-knob" />
      <span className="sr-only">{label}</span>
    </button>
  )
}

export function Panel({
  title, aside, children, className = '', tone = 'gear',
}: {
  title?: ReactNode
  aside?: ReactNode
  children: ReactNode
  className?: string
  tone?: 'gear' | 'well'
}) {
  return (
    <section className={`panel panel--${tone} ${className}`}>
      {(title || aside) && (
        <header className="panel-head">
          {title && <h3>{title}</h3>}
          {aside && <div className="panel-aside">{aside}</div>}
        </header>
      )}
      {children}
    </section>
  )
}

export function Key({
  children, onClick, kind = 'plain', disabled, title, type = 'button', className = '', active,
}: {
  children: ReactNode
  onClick?: () => void
  kind?: 'plain' | 'primary' | 'ghost' | 'danger' | 'live'
  disabled?: boolean
  title?: string
  type?: 'button' | 'submit'
  className?: string
  active?: boolean
}) {
  return (
    <button
      type={type}
      className={`key key--${kind} ${active ? 'is-active' : ''} ${className}`}
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-pressed={active}
    >
      {children}
    </button>
  )
}

export function Field({ label, children, hint }: { label: ReactNode; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}
