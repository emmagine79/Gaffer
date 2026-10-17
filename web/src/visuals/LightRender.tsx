import { useId } from 'react'
import { rgbCss, type RGB } from '../lib/color'

/**
 * The ML100R, front on: a compact body, a deep reflector around the COB, the
 * yoke it hangs in. The emitter glows in the light's live colour, read from
 * CSS variables, so it animates without React re-rendering. Pass `light` to
 * render a fixed look instead (thumbnails, previews).
 */
export function LightRender({
  light, size = 240, className = '', pulse = false,
}: {
  light?: { rgb: RGB; level: number }
  size?: number
  className?: string
  pulse?: boolean
}) {
  const id = useId().replace(/:/g, '')
  const live = light ? rgbCss(light.rgb) : 'var(--live)'
  const level = light ? String(light.level) : 'var(--ll)'

  return (
    <svg viewBox="0 0 240 260" width={size} height={size * (260 / 240)} className={`light-render ${pulse ? 'is-pulsing' : ''} ${className}`} aria-hidden="true">
      <defs>
        <linearGradient id={`${id}body`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#34353a" />
          <stop offset="0.55" stopColor="#222327" />
          <stop offset="1" stopColor="#18191c" />
        </linearGradient>
        <linearGradient id={`${id}bezel`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#5a5c63" />
          <stop offset="0.5" stopColor="#2a2b30" />
          <stop offset="1" stopColor="#131417" />
        </linearGradient>
        <radialGradient id={`${id}reflector`} cx="0.5" cy="0.5" r="0.5">
          <stop offset="0.25" stopColor="#1d1e22" />
          <stop offset="0.8" stopColor="#56585f" />
          <stop offset="1" stopColor="#8d9097" />
        </radialGradient>
        <radialGradient id={`${id}hot`} cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="0.45" style={{ stopColor: live }} />
          <stop offset="1" style={{ stopColor: live, stopOpacity: 0 }} />
        </radialGradient>
        <filter id={`${id}blur`} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="16" />
        </filter>
        <pattern id={`${id}cob`} width="4" height="4" patternUnits="userSpaceOnUse">
          <rect width="4" height="4" fill="#d8b04e" />
          <circle cx="2" cy="2" r="0.9" fill="#b38a2f" />
        </pattern>
      </defs>

      {/* yoke */}
      <path d="M22 118 C 22 196, 40 214, 120 214 C 200 214, 218 196, 218 118" fill="none" stroke="#2c2d32" strokeWidth="12" strokeLinecap="round" />
      <path d="M22 118 C 22 196, 40 214, 120 214 C 200 214, 218 196, 218 118" fill="none" stroke="#45474d" strokeWidth="2" strokeLinecap="round" transform="translate(-2 -3)" opacity="0.6" />
      <rect x="108" y="212" width="24" height="40" rx="4" fill="#232428" />
      <rect x="112" y="250" width="16" height="10" rx="2" fill="#18191c" />
      <circle cx="22" cy="118" r="13" fill="#3a3b41" />
      <circle cx="22" cy="118" r="5" fill="#16171a" />
      <circle cx="218" cy="118" r="13" fill="#3a3b41" />
      <circle cx="218" cy="118" r="5" fill="#16171a" />

      {/* body */}
      <rect x="34" y="30" width="172" height="168" rx="30" fill="#141518" transform="translate(4 6)" />
      <rect x="34" y="30" width="172" height="168" rx="30" fill={`url(#${id}body)`} />
      <rect x="35" y="31" width="170" height="166" rx="29" fill="none" stroke="rgb(255 255 255 / 0.07)" />
      {Array.from({ length: 5 }, (_, i) => (
        <rect key={i} x={186} y={70 + i * 18} width="10" height="3" rx="1.5" fill="#121315" />
      ))}

      {/* glow behind the emitter, scaled by intensity */}
      <circle cx="120" cy="112" r="64" filter={`url(#${id}blur)`} style={{ fill: live, opacity: `calc(${level} * 0.9)` }} className="light-render-bloom" />

      {/* bezel and reflector */}
      <circle cx="120" cy="112" r="66" fill={`url(#${id}bezel)`} />
      <circle cx="120" cy="112" r="58" fill={`url(#${id}reflector)`} />
      <circle cx="120" cy="112" r="58" style={{ fill: live, opacity: `calc(${level} * 0.35)` }} />
      {Array.from({ length: 12 }, (_, i) => {
        const a = (i / 12) * Math.PI * 2
        return (
          <line key={i} x1={120 + Math.cos(a) * 26} y1={112 + Math.sin(a) * 26} x2={120 + Math.cos(a) * 56} y2={112 + Math.sin(a) * 56}
            stroke="rgb(255 255 255 / 0.05)" strokeWidth="1" />
        )
      })}

      {/* COB: yellow phosphor when off, white-hot core when on */}
      <rect x="101" y="93" width="38" height="38" rx="5" fill={`url(#${id}cob)`} />
      <rect x="101" y="93" width="38" height="38" rx="5" fill={`url(#${id}hot)`} style={{ opacity: `min(1, calc(${level} * 1.6))` }} />
      <rect x="99" y="91" width="42" height="42" rx="6" fill="none" stroke="#0f1012" strokeWidth="3" />

      {/* glass glint */}
      <path d="M78 76 A 58 58 0 0 1 132 56" fill="none" stroke="rgb(255 255 255 / 0.18)" strokeWidth="3" strokeLinecap="round" />

      {/* model plate */}
      <text x="120" y="188" textAnchor="middle" fontSize="11" fontWeight="600" fill="#7c7f86" style={{ fontStretch: '125%', letterSpacing: '0.06em' }}>ML100R</text>
    </svg>
  )
}
