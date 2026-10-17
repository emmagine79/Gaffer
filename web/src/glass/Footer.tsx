import { openWindow, type Surface } from '../app/surface'
import type { LightView } from '../lib/types'
import { useStudio } from '../state/store'

type Tone = 'ok' | 'busy' | 'off'

/** A driver reports that the brand's own app holds a light (the service's `held`). */
const held = (l: LightView) => l.held === true

function status(socketOpen: boolean, link: string | undefined, lights: LightView[]): { text: string; tone: Tone } {
  if (!socketOpen) return { text: 'Gaffer is not running', tone: 'off' }
  const holder = lights.find(held)
  if (holder) return { text: `${holder.name} is held by the ${holder.caps.brand} app`, tone: 'busy' }
  if (link === 'scanning' || link === 'connecting' || link === 'backoff') return { text: 'Syncing', tone: 'busy' }
  if (lights.length === 0) return { text: 'No lights yet', tone: 'off' }
  const n = lights.filter((l) => l.online && l.reachable !== false).length
  return { text: `${n} ${n === 1 ? 'light' : 'lights'} connected`, tone: n > 0 ? 'ok' : 'off' }
}

/** "3 lights connected" or "Syncing", and Open Gaffer in the menu-bar panel. */
export function Footer({ surface }: { surface: Surface }) {
  const socketOpen = useStudio((s) => s.socketOpen)
  const link = useStudio((s) => s.link?.status)
  const lights = useStudio((s) => s.lights)
  const { text, tone } = status(socketOpen, link, lights)
  return (
    <footer className="g-foot">
      <span className="g-status" role="status"><span className={`g-dot g-dot--${tone}`} />{text}</span>
      {surface === 'menubar' && (
        <button type="button" className="g-open" onClick={() => openWindow()}>Open Gaffer</button>
      )}
    </footer>
  )
}
