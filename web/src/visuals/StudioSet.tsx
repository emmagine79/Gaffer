import { useId } from 'react'
import { rgbCss, type RGB } from '../lib/color'
import { SUBJECTS } from './scenes'
import './visuals.css'

const LIGHT = { x: 150, y: 250 } // the emitter, in set coordinates

/**
 * A small studio: seamless paper, a subject, and the ML100R on a stand.
 *
 * Lighting is compositing, not painting: an ambient copy of the set sits at
 * low exposure, and a lit copy is multiplied by the light's colour and masked
 * by a falloff around where the beam lands. Colour and intensity come from
 * the live CSS variables unless a fixed `light` is passed.
 */
export function StudioSet({
  subject = 'bookshelf', light, className = '', rig = true, label,
}: {
  subject?: string
  light?: { rgb: RGB; level: number }
  className?: string
  rig?: boolean
  label?: string
}) {
  const uid = useId().replace(/:/g, '')
  const s = SUBJECTS.find((x) => x.id === subject) ?? SUBJECTS[0]
  const live = light ? rgbCss(light.rgb) : 'var(--live)'
  const level = light ? String(light.level) : 'var(--ll)'
  const { focus } = s
  const beam = `M ${LIGHT.x + 26} ${LIGHT.y - 14} L ${focus.x - 40} ${focus.y - s.beamTo} L ${focus.x - 40} ${focus.y + s.beamTo} L ${LIGHT.x + 26} ${LIGHT.y + 14} Z`

  return (
    <svg viewBox="0 0 1000 600" className={`studio-set ${className}`} role="img" aria-label={label ?? `${s.name} lit by the light`} preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id={`${uid}paper`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#d9d5cc" />
          <stop offset="0.72" stopColor="#cfcabf" />
          <stop offset="0.86" stopColor="#c2bcb0" />
          <stop offset="1" stopColor="#b3ad9f" />
        </linearGradient>
        <g id={`${uid}scene`}>
          <rect width="1000" height="600" fill={`url(#${uid}paper)`} />
          <path d="M0 470 Q 0 520 60 528 L 1000 528 L 1000 600 L 0 600 Z" fill="#aaa497" opacity="0.5" />
          {s.draw()}
        </g>
        <radialGradient id={`${uid}falloff`} gradientUnits="userSpaceOnUse" cx={focus.x - 60} cy={focus.y} r={Math.max(focus.rx, focus.ry)}
          gradientTransform={`translate(${focus.x - 60} ${focus.y}) scale(1 ${focus.ry / Math.max(focus.rx, focus.ry)}) translate(${-(focus.x - 60)} ${-focus.y})`}>
          <stop offset="0" stopColor="#fff" />
          <stop offset="0.55" stopColor="#fff" stopOpacity="0.75" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
        <radialGradient id={`${uid}spill`} gradientUnits="userSpaceOnUse" cx={LIGHT.x} cy={LIGHT.y} r="520">
          <stop offset="0" stopColor="#fff" stopOpacity="0.55" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
        <mask id={`${uid}mask`} maskUnits="userSpaceOnUse" x="0" y="0" width="1000" height="600">
          <rect width="1000" height="600" fill={`url(#${uid}falloff)`} />
          <rect width="1000" height="600" fill={`url(#${uid}spill)`} />
        </mask>
        <linearGradient id={`${uid}beam`} gradientUnits="userSpaceOnUse" x1={LIGHT.x} y1={LIGHT.y} x2={focus.x} y2={focus.y}>
          <stop offset="0" style={{ stopColor: live, stopOpacity: 0.9 }} />
          <stop offset="1" style={{ stopColor: live, stopOpacity: 0 }} />
        </linearGradient>
        <filter id={`${uid}soft`} x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="18" />
        </filter>
        <filter id={`${uid}glow`} x="-200%" y="-200%" width="500%" height="500%">
          <feGaussianBlur stdDeviation="10" />
        </filter>
      </defs>

      {/* ambient: the room with the light off */}
      <use href={`#${uid}scene`} />
      <rect width="1000" height="600" fill="#07080b" opacity="0.8" />

      {/* key light: albedo x light colour, falling off from the beam */}
      <g mask={`url(#${uid}mask)`} style={{ opacity: level }} className="studio-set-lit">
        <use href={`#${uid}scene`} />
        <rect width="1000" height="600" style={{ fill: live, mixBlendMode: 'multiply' }} />
      </g>

      {/* haze in the beam */}
      <path d={beam} fill={`url(#${uid}beam)`} filter={`url(#${uid}soft)`}
        style={{ mixBlendMode: 'screen', opacity: `calc(${level} * 0.32)` }} />

      {rig && (
        <g className="studio-set-rig">
          {/* stand */}
          <path d={`M ${LIGHT.x} ${LIGHT.y + 40} L ${LIGHT.x} 560`} stroke="#1a1b1e" strokeWidth="9" />
          <path d={`M ${LIGHT.x} 556 L ${LIGHT.x - 70} 600 M ${LIGHT.x} 556 L ${LIGHT.x + 70} 600 M ${LIGHT.x} 556 L ${LIGHT.x} 600`} stroke="#1a1b1e" strokeWidth="7" strokeLinecap="round" />
          <rect x={LIGHT.x - 8} y={LIGHT.y + 120} width="16" height="22" rx="3" fill="#2a2b2f" />
          {/* yoke and head, aimed at the subject */}
          <g transform={`rotate(${(Math.atan2(focus.y - LIGHT.y, focus.x - LIGHT.x) * 180) / Math.PI} ${LIGHT.x} ${LIGHT.y})`}>
            <path d={`M ${LIGHT.x - 18} ${LIGHT.y - 46} Q ${LIGHT.x - 44} ${LIGHT.y} ${LIGHT.x - 18} ${LIGHT.y + 46}`} stroke="#2a2b2f" strokeWidth="6" fill="none" />
            <rect x={LIGHT.x - 44} y={LIGHT.y - 40} width="66" height="80" rx="14" fill="#232428" />
            <rect x={LIGHT.x - 44} y={LIGHT.y - 40} width="66" height="80" rx="14" fill="none" stroke="rgb(255 255 255 / 0.08)" />
            <rect x={LIGHT.x + 18} y={LIGHT.y - 30} width="12" height="60" rx="4" fill="#3a3b41" />
            <rect x={LIGHT.x + 26} y={LIGHT.y - 24} width="6" height="48" rx="3" style={{ fill: live, opacity: `max(0.12, ${level})` }} />
            <ellipse cx={LIGHT.x + 32} cy={LIGHT.y} rx="16" ry="34" filter={`url(#${uid}glow)`} style={{ fill: live, opacity: `calc(${level} * 0.9)` }} />
          </g>
          <path d={`M ${LIGHT.x} ${LIGHT.y + 30} L ${LIGHT.x} ${LIGHT.y + 130}`} stroke="#1a1b1e" strokeWidth="7" />
        </g>
      )}
    </svg>
  )
}
