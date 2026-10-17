import { useId } from 'react'

/**
 * The line drawing of the light with its beam, from design/round4/d-switch.html.
 * The beam is drawn in var(--beam-draw), the light's real colour (set on the panel),
 * and fades with brightness; a light that is off has no beam.
 */
export function Lamp({ level }: { level: number }) {
  const id = `beam${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const strength = level > 0 ? 0.35 + 0.65 * level : 0
  return (
    <svg className="g-art" viewBox="0 0 400 100" aria-hidden="true" data-level={level.toFixed(2)}>
      <defs>
        <linearGradient id={id} x1="0" x2="1">
          <stop offset="0" style={{ stopColor: 'var(--beam-draw)', stopOpacity: 0.55 * strength }} />
          <stop offset="1" style={{ stopColor: 'var(--beam-draw)', stopOpacity: 0 }} />
        </linearGradient>
      </defs>
      <path d="M166 30 L400 2 L400 98 L166 70 Z" fill={`url(#${id})`} />
      <g style={{ stroke: 'var(--beam-draw)', strokeOpacity: 0.5 * strength }} strokeDasharray="3 7" strokeLinecap="round">
        <path d="M176 42 L360 26" />
        <path d="M176 50 L372 50" />
        <path d="M176 58 L360 74" />
      </g>
      <g fill="none" style={{ stroke: 'var(--ink)' }} strokeWidth="2" strokeLinejoin="round">
        <rect x="70" y="27" width="70" height="46" rx="8" />
        <path d="M82 27v46M94 27v46M106 27v46" />
        <path d="M140 33 L166 23 L166 77 L140 67 Z" />
        <path d="M105 73v14M78 87h54" />
        <circle cx="105" cy="50" r="5" />
      </g>
    </svg>
  )
}
