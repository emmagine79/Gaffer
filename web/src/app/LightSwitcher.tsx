import { Check, ChevronsUpDown, Plus, Power, Waypoints } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { emission } from '../lib/color'
import type { LightView } from '../lib/types'
import { useStudio } from '../state/store'
import { KIND_SHORT, LightGlyph, formOf } from '../visuals/LightGlyph'
import './switcher.css'

export function statusOf(light: LightView, linkUp: boolean): { tone: 'ok' | 'warn' | 'off' | 'away'; text: string } {
  if (!light.online) return { tone: 'away', text: 'On another network' }
  if (!linkUp) return { tone: 'off', text: 'Not connected' }
  if (light.reachable === false) return { tone: 'warn', text: 'Not answering' }
  if (!light.state.power) return { tone: 'off', text: 'Off' }
  return { tone: 'ok', text: `${Math.round(light.state.brightness)}%` }
}

export function LightBadge({ light, size = 34 }: { light: LightView; size?: number }) {
  const { rgb, level } = emission(light.state)
  return <LightGlyph form={formOf(light.model)} rgb={rgb} level={level} off={!light.state.power} size={size} />
}

/** Which light every control on the page is talking to, and the way to change it. */
export function LightSwitcher() {
  const lights = useStudio((s) => s.lights)
  const light = useStudio((s) => s.light)
  const linkUp = useStudio((s) => s.link?.status === 'connected')
  const gateway = useStudio((s) => s.link?.gateway)
  const select = useStudio((s) => s.select)
  const powerOf = useStudio((s) => s.powerOf)
  const setTab = useStudio((s) => s.setTab)
  const setAddLight = useStudio((s) => s.setAddLight)
  const [open, setOpen] = useState(false)
  const [at, setAt] = useState({ left: 0, top: 0 })
  const ref = useRef<HTMLDivElement>(null)
  const menu = useRef<HTMLDivElement>(null)

  // The rail scrolls, so the menu lives in a portal, placed under the button.
  useLayoutEffect(() => {
    if (!open || !ref.current) return
    const r = ref.current.getBoundingClientRect()
    setAt({ left: r.left, top: r.bottom + 6 })
  }, [open])

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent) {
        if (e.key === 'Escape') setOpen(false)
        return
      }
      const target = e.target as Node
      if (!ref.current?.contains(target) && !menu.current?.contains(target)) setOpen(false)
    }
    window.addEventListener('pointerdown', close)
    window.addEventListener('keydown', close)
    return () => { window.removeEventListener('pointerdown', close); window.removeEventListener('keydown', close) }
  }, [open])

  if (!light) {
    return (
      <button type="button" className="switcher switcher--empty" onClick={() => setAddLight(true)}>
        <span className="switcher-plus"><Plus size={16} /></span>
        <span className="switcher-text"><strong>Add a light</strong><small>No lights yet</small></span>
      </button>
    )
  }

  return (
    <div className="switcher-wrap" ref={ref}>
      <button type="button" className={`switcher ${open ? 'is-open' : ''}`} onClick={() => setOpen(!open)}
        aria-haspopup="listbox" aria-expanded={open} title="Choose which light to control (L)">
        <LightBadge light={light} />
        <span className="switcher-text">
          <strong>{light.name}</strong>
          <small>{light.model} · {KIND_SHORT[light.kind]}</small>
        </span>
        <ChevronsUpDown size={15} className="switcher-chev" />
      </button>

      {open && createPortal(
        <div className="switcher-menu" role="listbox" aria-label="Lights" ref={menu} style={{ left: at.left, top: at.top }}>
          <p className="switcher-menu-head">{lights.length} {lights.length === 1 ? 'light' : 'lights'}</p>
          {lights.map((l) => {
            const status = statusOf(l, linkUp)
            const on = l.id === light.id
            return (
              <div key={l.id} className={`switcher-row ${on ? 'is-on' : ''}`} role="option" aria-selected={on}>
                <button type="button" className="switcher-pick" onClick={() => { select(l.id, { connect: true }); setOpen(false) }}>
                  <LightBadge light={l} size={30} />
                  <span className="switcher-text">
                    <strong>{l.name}{gateway === l.id && <span className="switcher-gw" title="The studio's Bluetooth link goes through this light">link</span>}</strong>
                    <small><i className={`dot dot--${status.tone}`} />{l.model} · {status.text}</small>
                  </span>
                  {on && <Check size={15} className="switcher-check" />}
                </button>
                <button type="button" className={`switcher-power ${l.state.power ? 'is-on' : ''}`}
                  onClick={() => powerOf(l.id, !l.state.power, 0.3)} disabled={!l.online}
                  aria-label={`${l.state.power ? 'Switch off' : 'Switch on'} ${l.name}`}>
                  <Power size={14} strokeWidth={2.4} />
                </button>
              </div>
            )
          })}
          <div className="switcher-foot">
            <button type="button" onClick={() => { setAddLight(true); setOpen(false) }}><Plus size={15} /> Add a light</button>
            <button type="button" onClick={() => { setTab('mesh'); setOpen(false) }}><Waypoints size={15} /> Manage lights</button>
          </div>
        </div>,
        document.body,
      )}
    </div>
  )
}
