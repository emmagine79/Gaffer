import { useCallback, useRef, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { clamp } from '../lib/color'
import './controls.css'

interface Props {
  value: number
  min: number
  max: number
  step?: number
  onChange: (value: number) => void
  label: string
  /** CSS background for the track; when given, no fill is drawn. */
  track?: string
  format?: (value: number) => ReactNode
  vertical?: boolean
  showValue?: boolean
  disabled?: boolean
  className?: string
  /** Snap points drawn as ticks under the track. */
  ticks?: number[]
}

const snap = (v: number, step: number, min: number) => Math.round((v - min) / step) * step + min

export function Slider({
  value, min, max, step = 1, onChange, label, track, format, vertical = false,
  showValue = true, disabled = false, className = '', ticks,
}: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const span = max - min || 1
  const fraction = clamp((value - min) / span, 0, 1)

  const fromPointer = useCallback((e: PointerEvent) => {
    const rect = ref.current?.getBoundingClientRect()
    if (!rect) return
    const f = vertical ? 1 - (e.clientY - rect.top) / rect.height : (e.clientX - rect.left) / rect.width
    const next = clamp(snap(min + clamp(f, 0, 1) * span, step, min), min, max)
    if (next !== value) onChange(Number(next.toFixed(4)))
  }, [vertical, min, span, step, max, value, onChange])

  const onKey = (e: KeyboardEvent) => {
    const big = e.shiftKey ? 10 : 1
    const deltas: Record<string, number> = {
      ArrowRight: step * big, ArrowUp: step * big, ArrowLeft: -step * big, ArrowDown: -step * big,
      PageUp: span / 10, PageDown: -span / 10,
    }
    let next: number | null = null
    if (e.key in deltas) next = value + deltas[e.key]
    if (e.key === 'Home') next = min
    if (e.key === 'End') next = max
    if (next === null) return
    e.preventDefault()
    onChange(Number(clamp(snap(next, step, min), min, max).toFixed(4)))
  }

  const pos = `${fraction * 100}%`
  return (
    <div className={`slider ${vertical ? 'slider--v' : ''} ${disabled ? 'is-disabled' : ''} ${className}`}>
      <div
        ref={ref}
        className="slider-body"
        role="slider"
        tabIndex={disabled ? -1 : 0}
        aria-label={label}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={value}
        aria-orientation={vertical ? 'vertical' : 'horizontal'}
        onKeyDown={onKey}
        onPointerDown={(e) => {
          if (disabled) return
          ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
          fromPointer(e)
        }}
        onPointerMove={(e) => {
          if ((e.currentTarget as HTMLElement).hasPointerCapture(e.pointerId)) fromPointer(e)
        }}
      >
        <div className="slider-track" style={track ? { background: track } : undefined}>
          {!track && <div className="slider-fill" style={vertical ? { height: pos } : { width: pos }} />}
        </div>
        {ticks?.map((t) => (
          <span key={t} className="slider-tick" style={vertical
            ? { bottom: `${((t - min) / span) * 100}%` }
            : { left: `${((t - min) / span) * 100}%` }} />
        ))}
        <div className="slider-thumb" style={vertical ? { bottom: pos } : { left: pos }} />
      </div>
      {showValue && <output className="slider-value">{format ? format(value) : value}</output>}
    </div>
  )
}
