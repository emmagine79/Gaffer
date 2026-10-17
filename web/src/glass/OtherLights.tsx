import { useStudio } from '../state/store'
import { beamOf, summary } from './describe'

/** On a phone, the other lights sit under the panel (design/directions/a-glass.png). Tap one to open it. */
export function OtherLights() {
  const lights = useStudio((s) => s.lights)
  const selected = useStudio((s) => s.selected)
  const select = useStudio((s) => s.select)
  const others = lights.filter((l) => l.id !== selected)
  if (others.length === 0) return null
  return (
    <ul className="g-others" aria-label="Other lights">
      {others.map((l) => {
        const { css, level } = beamOf(l.state)
        return (
          <li key={l.id}>
            <button type="button" onClick={() => select(l.id)}>
              <span className="g-other-text">
                <span className="g-other-name">{l.name}</span>
                <small>{summary(l)}</small>
              </span>
              <span className="g-swatch" style={{ background: css, opacity: level > 0 ? 1 : 0.25 }} />
            </button>
          </li>
        )
      })}
    </ul>
  )
}
