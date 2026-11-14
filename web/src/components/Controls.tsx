import type { ReactNode } from 'react'
import './controls.css'

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
