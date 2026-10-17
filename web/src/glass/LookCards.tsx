import { useState, type ReactNode } from 'react'
import type { Scene } from '../lib/types'
import { EMPTY, useStudio } from '../state/store'

/** Room for three looks and All off, as in the mockup's four cards. */
const SHOWN = 3

const ICONS: [RegExp, ReactNode][] = [
  [/head|talk|interview|face/i, <g key="head"><circle cx="10" cy="7" r="3.5" /><path d="M3.5 18c1-4 3.6-6 6.5-6s5.5 2 6.5 6" /></g>],
  [/product|table|object/i, <g key="product"><rect x="4" y="7" width="12" height="10" rx="2" /><path d="M7 7V5h6v2" /></g>],
  [/mood|night|dark|low/i, <path key="moon" d="M15 12.5A6.5 6.5 0 0 1 7.5 5a6.5 6.5 0 1 0 7.5 7.5Z" />],
]
const STAR = <path d="M10 3l2 4.6 5 .5-3.8 3.3 1.1 4.9L10 13.8 5.7 16.3l1.1-4.9L3 8.1l5-.5Z" />
const POWER = <><path d="M10 3v7" /><path d="M6 5.5a6 6 0 1 0 8 0" /></>

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      {children}
    </svg>
  )
}

/**
 * The look cards under the controls. SPEC-010 brings looks that set every light with
 * their own fade; until then the cards apply lumen's saved scenes to the selected light.
 */
export function LookCards() {
  const scenes = useStudio((s) => (s.store?.scenes as Scene[] | undefined) ?? EMPTY)
  const lights = useStudio((s) => s.lights)
  const send = useStudio((s) => s.send)
  const powerOf = useStudio((s) => s.powerOf)
  const [last, setLast] = useState<string | null>(null)
  const allOff = lights.length > 0 && lights.every((l) => !l.state.power)
  const shown = scenes.slice(0, SHOWN)
  return (
    <div className="g-cards" style={{ gridTemplateColumns: `repeat(${shown.length + 1}, minmax(0, 1fr))` }}>
      {shown.map((scene) => (
        <button
          key={scene.id}
          type="button"
          className={`g-card ${last === scene.id && !allOff ? 'sel' : ''}`}
          onClick={() => {
            setLast(scene.id)
            send({ type: 'scene.apply', id: scene.id })
          }}
        >
          <Icon>{ICONS.find(([re]) => re.test(scene.name))?.[1] ?? STAR}</Icon>
          <span>{scene.name}</span>
        </button>
      ))}
      <button
        type="button"
        className={`g-card ${allOff ? 'sel' : ''}`}
        onClick={() => {
          setLast(null)
          lights.forEach((l) => powerOf(l.id, false))
        }}
      >
        <Icon>{POWER}</Icon>
        <span>All off</span>
      </button>
    </div>
  )
}
