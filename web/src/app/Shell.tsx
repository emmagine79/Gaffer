import { useState, type CSSProperties } from 'react'
import { beamOf } from '../glass/describe'
import { Footer } from '../glass/Footer'
import { Glass } from '../glass/Glass'
import { OtherLights } from '../glass/OtherLights'
import { CueBar } from '../cues/CueBar'
import { CueEditor } from '../cues/CueEditor'
import { useCueKey } from '../cues/cues'
import { PhonePanel } from '../phone/PhonePanel'
import { LookEditor } from '../looks/LookEditor'
import { useLookKeys } from '../looks/looks'
import { ScheduleEditor } from '../schedules/ScheduleEditor'
import { useTabKey } from '../desk/useTabKey'
import { useStudio } from '../state/store'
import { AddLight, DeskSlot, Groups } from './slots'
import { readSurface, rememberView, rememberedView, type Surface, type View } from './surface'

const SURFACE: Surface = readSurface()

/** Neutral warm white for the panel tint before any light is known (the mockup's #FFEFE1). */
const NO_LIGHT = 'rgb(255 239 225)'

/**
 * The panel every surface shows: the top switch, then Glass or the desk, then the footer.
 * The panel picks up a tint of the selected light's colour (a-glass.html).
 */
export function Shell() {
  const [view, setView] = useState<View>(() => rememberedView(SURFACE))
  const state = useStudio((s) => s.state)
  const beam = state ? beamOf(state).css : NO_LIGHT
  useLookKeys()
  useCueKey(SURFACE)
  const choose = (next: View) => {
    setView(next)
    rememberView(SURFACE, next)
  }
  useTabKey(() => choose(view === 'glass' ? 'desk' : 'glass'))
  return (
    <div className="surface">
      <main className="glass" style={{ '--beam': beam } as CSSProperties} data-view={view}>
        <ViewSwitch view={view} onChange={choose} />
        {view === 'glass' ? <Glass /> : <DeskSlot onOpenLight={() => choose('glass')} />}
        {SURFACE !== 'menubar' && view === 'glass' && <Groups />}
        <CueBar />
        <Footer surface={SURFACE} />
        {SURFACE === 'phone' && view === 'glass' && <OtherLights />}
      </main>
      {SURFACE === 'window' && <LookEditor />}
      {SURFACE === 'window' && <CueEditor />}
      {SURFACE === 'window' && <ScheduleEditor />}
      <AddLight />
      <Toasts />
      {SURFACE === 'window' && <PhonePanel />}
    </div>
  )
}

function ViewSwitch({ view, onChange }: { view: View; onChange: (view: View) => void }) {
  return (
    <div className="g-switch" role="group" aria-label="View">
      <button type="button" className={view === 'glass' ? 'sel' : ''} aria-pressed={view === 'glass'} onClick={() => onChange('glass')}>
        <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
          <circle cx="7" cy="7" r="5" /><path d="M7 2a5 5 0 0 1 0 10Z" fill="currentColor" />
        </svg>
        One light
      </button>
      <button type="button" className={view === 'desk' ? 'sel' : ''} aria-pressed={view === 'desk'} onClick={() => onChange('desk')}>
        <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
          <path d="M3 2v10M7 2v10M11 2v10" /><path d="M1.5 8h3M5.5 5h3M9.5 9h3" strokeWidth="2.2" />
        </svg>
        All lights
      </button>
    </div>
  )
}

function Toasts() {
  const toasts = useStudio((s) => s.toasts)
  const dismiss = useStudio((s) => s.dismissToast)
  if (toasts.length === 0) return null
  return (
    <div className="g-toasts" role="status">
      {toasts.map((t) => (
        <button key={t.id} type="button" className={`g-toast g-toast--${t.kind}`} onClick={() => dismiss(t.id)}>{t.text}</button>
      ))}
    </div>
  )
}
