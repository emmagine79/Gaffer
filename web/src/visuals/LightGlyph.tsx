import { useId } from 'react'
import { rgbCss, type RGB } from '../lib/color'
import type { LightKind } from '../lib/types'

export type LightForm = 'cob' | 'tube' | 'panel'

/** The shape a model comes in, from its name: the range names its families consistently. */
export function formOf(model: string): LightForm {
  const name = model.toUpperCase().replace(/\s+/g, '')
  if (/^(TL|TPC|TP|LC)\d/.test(name) || name.startsWith('LC')) return 'tube'
  if (/^(LDX|LD|LP|P\d|FL|FH|F\d|LF)/.test(name)) return 'panel'
  return 'cob'
}

export const KIND_SHORT: Record<LightKind, string> = {
  rgb: 'RGB',
  colour: 'Colour',
  bicolour: 'Bi-colour',
  daylight: 'Daylight',
  unsupported: 'Unsupported',
}

/**
 * A light as a small front-on drawing: a COB monolight, a tube or a panel,
 * its emitter lit in the light's colour at its level. Used wherever a light
 * is named (switcher, floor plan, pairing), so each one is recognisable.
 */
export function LightGlyph({
  form, rgb, level, size = 40, off = false, className = '',
}: {
  form: LightForm
  rgb: RGB
  level: number
  size?: number
  off?: boolean
  className?: string
}) {
  const id = useId().replace(/:/g, '')
  const glow = off ? 0 : Math.max(0.12, Math.min(1, level))
  const lit = off ? '#2c2d32' : rgbCss(rgb)
  const halo = off ? 'transparent' : rgbCss(rgb, 0.18 + glow * 0.5)

  return (
    <svg viewBox="0 0 48 48" width={size} height={size} className={`glyph glyph--${form} ${className}`} aria-hidden="true">
      <defs>
        <radialGradient id={`${id}h`} cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor={halo} />
          <stop offset="1" stopColor="transparent" />
        </radialGradient>
        <radialGradient id={`${id}e`} cx="0.5" cy="0.45" r="0.6">
          <stop offset="0" stopColor={off ? '#3a3b41' : '#ffffff'} stopOpacity={off ? 1 : 0.55 + glow * 0.45} />
          <stop offset="0.55" stopColor={lit} />
          <stop offset="1" stopColor={off ? '#202125' : rgbCss(rgb, 0.75)} />
        </radialGradient>
        <linearGradient id={`${id}b`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#45464c" />
          <stop offset="1" stopColor="#1b1c20" />
        </linearGradient>
      </defs>
      <circle cx="24" cy="24" r="23" fill={`url(#${id}h)`} />
      {form === 'cob' && (
        <>
          <circle cx="24" cy="24" r="15" fill={`url(#${id}b)`} stroke="#5b5d64" strokeWidth="1.2" />
          <circle cx="24" cy="24" r="11.2" fill="#121316" />
          <circle cx="24" cy="24" r="7.4" fill={`url(#${id}e)`} />
          <path d="M14.5 15.8a13 13 0 0 1 9-4.3" stroke="rgb(255 255 255 / 0.28)" strokeWidth="1.3" fill="none" strokeLinecap="round" />
        </>
      )}
      {form === 'tube' && (
        <>
          <rect x="6" y="19.5" width="36" height="9" rx="4.5" fill={`url(#${id}b)`} stroke="#5b5d64" strokeWidth="1" />
          <rect x="9.5" y="21.6" width="29" height="4.8" rx="2.4" fill={`url(#${id}e)`} />
          <rect x="3.6" y="21.2" width="3.2" height="5.6" rx="1" fill="#2a2b30" />
          <rect x="41.2" y="21.2" width="3.2" height="5.6" rx="1" fill="#2a2b30" />
        </>
      )}
      {form === 'panel' && (
        <>
          <rect x="9" y="11" width="30" height="26" rx="3.2" fill={`url(#${id}b)`} stroke="#5b5d64" strokeWidth="1.1" />
          <rect x="12" y="14" width="24" height="20" rx="1.6" fill={`url(#${id}e)`} />
          {[17, 21, 25, 29].map((y) => [17, 21, 25, 29, 33].map((x) => (
            <circle key={`${x}-${y}`} cx={x - 1} cy={y} r="0.7" fill={off ? '#3a3b41' : 'rgb(255 255 255 / 0.45)'} />
          )))}
        </>
      )}
    </svg>
  )
}
