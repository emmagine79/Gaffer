import { useState, type CSSProperties, type MouseEvent } from 'react'
import { beamOf } from '../glass/describe'
import { Footer } from '../glass/Footer'
import { Glass } from '../glass/Glass'
import { OtherLights } from '../glass/OtherLights'
import { useTabKey } from '../desk/useTabKey'
import { useStudio } from '../state/store'
import { AddLight, DeskSlot } from './slots'
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
        <Footer surface={SURFACE} />
        {SURFACE === 'phone' && view === 'glass' && <OtherLights />}
      </main>
      <AddLight />
      <Toasts />
    </div>
  )
}

function ViewSwitch({ view, onChange }: { view: View; onChange: (view: View) => void }) {
  // A mouse or touch click hands focus back to the page, so Tab still flips the view afterwards
  // (see desk/useTabKey.ts). Enter or Space on the focused button (detail 0) keeps focus on it.
  const pick = (e: MouseEvent<HTMLButtonElement>, next: View) => {
    if (e.detail > 0) e.currentTarget.blur()
    onChange(next)
  }
  return (
    <div className="g-switch" role="group" aria-label="View">
      <button type="button" className={view === 'glass' ? 'sel' : ''} aria-pressed={view === 'glass'} onClick={(e) => pick(e, 'glass')}>
        <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
          <circle cx="7" cy="7" r="5" /><path d="M7 2a5 5 0 0 1 0 10Z" fill="currentColor" />
        </svg>
        One light
      </button>
      <button type="button" className={view === 'desk' ? 'sel' : ''} aria-pressed={view === 'desk'} onClick={(e) => pick(e, 'desk')}>
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
