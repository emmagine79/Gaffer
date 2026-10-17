import { useCallback, useRef, type KeyboardEvent, type PointerEvent } from 'react'
import { hsvToRgb, rgbCss } from '../lib/color'
import './wheel.css'

/**
 * Hue around the rim (0 at the top, clockwise), saturation from the centre
 * out. Drawn with CSS gradients, so it costs nothing to re-render.
 */
export function HueWheel({
  hue, sat, onChange, size = 300, marks = [],
}: {
  hue: number
  sat: number
  onChange: (hue: number, sat: number) => void
  size?: number
  marks?: { hue: number; sat: number }[]
}) {
  const ref = useRef<HTMLDivElement>(null)

  const fromPointer = useCallback((e: PointerEvent) => {
    const rect = ref.current?.getBoundingClientRect()
    if (!rect) return
    const x = e.clientX - (rect.left + rect.width / 2)
    const y = e.clientY - (rect.top + rect.height / 2)
    const radius = rect.width / 2
    const h = (Math.atan2(x, -y) * 180) / Math.PI
    const s = Math.min(1, Math.hypot(x, y) / radius) * 100
    onChange(Math.round((h + 360) % 360), Math.round(s))
  }, [onChange])

  const onKey = (e: KeyboardEvent) => {
    const step = e.shiftKey ? 10 : 1
    if (e.key === 'ArrowLeft') onChange((hue - step + 360) % 360, sat)
    else if (e.key === 'ArrowRight') onChange((hue + step) % 360, sat)
    else if (e.key === 'ArrowUp') onChange(hue, Math.min(100, sat + step))
    else if (e.key === 'ArrowDown') onChange(hue, Math.max(0, sat - step))
    else return
    e.preventDefault()
  }

  const pos = (h: number, s: number) => {
    const a = (h * Math.PI) / 180
    const r = (s / 100) * 50
    return { left: `${50 + Math.sin(a) * r}%`, top: `${50 - Math.cos(a) * r}%` }
  }

  return (
    <div
      ref={ref}
      className="wheel"
      style={{ width: size, height: size }}
      role="slider"
      tabIndex={0}
      aria-label="Hue and saturation"
      aria-valuetext={`Hue ${hue} degrees, saturation ${sat} percent`}
      aria-valuenow={hue}
      aria-valuemin={0}
      aria-valuemax={360}
      onKeyDown={onKey}
      onPointerDown={(e) => {
        ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
        fromPointer(e)
      }}
      onPointerMove={(e) => {
        if ((e.currentTarget as HTMLElement).hasPointerCapture(e.pointerId)) fromPointer(e)
      }}
    >
      <div className="wheel-disc" />
      {marks.map((m, i) => (
        <span key={i} className="wheel-mark" style={{ ...pos(m.hue, m.sat), background: rgbCss(hsvToRgb(m.hue, m.sat)) }} />
      ))}
      <span className="wheel-puck" style={{ ...pos(hue, sat), background: rgbCss(hsvToRgb(hue, sat)) }} />
    </div>
  )
}
