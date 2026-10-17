import { useState, type ReactNode } from 'react'
import { useStudio } from '../state/store'
import { allOff, allOn, applyLook, useLooks } from './looks'
import './looks.css'

/** Room for three looks and All off, as in the mockup's four cards. The rest sit under "More looks". */
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
 * The look cards under the controls. Each card applies a look to all its lights over the
 * look's own fade (SPEC-010). The first three show as cards; any more are one tap away
 * under "More looks", so every look can be reached from the panel.
 */
export function LookCards() {
  const looks = useLooks()
  const lights = useStudio((s) => s.lights)
  const current = useStudio((s) => s.look)
  const [more, setMore] = useState(false)
  const allOffNow = lights.length > 0 && lights.every((l) => !l.state.power)
  const shown = looks.slice(0, SHOWN)
  const rest = looks.slice(SHOWN)
  return (
    <>
      <div className="g-cards" style={{ gridTemplateColumns: `repeat(${shown.length + 1}, minmax(0, 1fr))` }}>
        {shown.map((look) => (
          <button
            key={look.id}
            type="button"
            className={`g-card ${current?.id === look.id && !allOffNow ? 'sel' : ''}`}
            onClick={() => applyLook(look.id)}
          >
            <Icon>{ICONS.find(([re]) => re.test(look.name))?.[1] ?? STAR}</Icon>
            <span>{look.name}</span>
          </button>
        ))}
        <button type="button" className="g-card" onClick={allOffNow ? allOn : () => void allOff()}>
          <Icon>{POWER}</Icon>
          <span>{allOffNow ? 'All on' : 'All off'}</span>
        </button>
      </div>
      {looks.length === 0 && <p className="g-dim g-nolooks">No looks yet. Save one in the Gaffer window.</p>}
      {rest.length > 0 && (
        <div className="g-more">
          <button type="button" className="g-more-toggle" aria-expanded={more} onClick={() => setMore(!more)}>
            {more ? 'Fewer looks' : `More looks (${rest.length})`}
          </button>
          {more && (
            <ul className="g-more-list">
              {rest.map((look) => (
                <li key={look.id}>
                  <button type="button" className={current?.id === look.id && !allOffNow ? 'sel' : ''} onClick={() => applyLook(look.id)}>
                    {look.name}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </>
  )
}
