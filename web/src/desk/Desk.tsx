import { useEffect, useRef, useState, type CSSProperties, type PointerEvent } from 'react'
import { allOn } from '../looks/looks'
import { Slider } from '../components/Slider'
import type { LightView } from '../lib/types'
import { beamOf, modelLine, readout } from '../glass/describe'
import { useStudio } from '../state/store'
import { scaleLevels } from './levels'
import { useDeskLooks } from './looks'
import './desk.css'

/** How long a finger rests on a strip before it counts as a selection (phone). */
const LONG_PRESS_MS = 500

/**
 * How far a held finger may drift, in CSS pixels, before the press stops counting as a selection.
 * Apple documents 10 points as the default for UILongPressGestureRecognizer.allowableMovement
 * (developer.apple.com/documentation/uikit/uilongpressgesturerecognizer/allowablemovement).
 */
const LONG_PRESS_DRIFT = 10

/** One drag of a grouped fader: every picked light's level when it began, and the newest level asked for. */
interface Drag { anchor: string; start: Record<string, number>; level: number | null; frame: number }

const sendMany = (d: Drag) =>
  useStudio.getState().send({
    type: 'set.many', anchor: d.anchor, lights: Object.keys(d.start), start_levels: d.start, brightness: d.level,
  })

/**
 * The lighting desk (design/directions/b-desk.html): one strip per light, numbered looks.
 * Shift-click or long-press selects lights; dragging one selected fader sends one
 * set.many and the service scales the others (service/gaffer/levels.py).
 */
export function Desk({ onOpenLight }: { onOpenLight: () => void }) {
  const ready = useStudio((s) => s.ready)
  const lights = useStudio((s) => s.lights)
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set())
  const picks = lights.filter((l) => picked.has(l.id)).map((l) => l.id)

  const toggle = (id: string) =>
    setPicked((now) => {
      const next = new Set(now)
      if (!next.delete(id)) next.add(id)
      return next
    })

  if (!ready) return <p className="g-empty">Opening Gaffer</p>
  if (lights.length === 0) return <p className="g-empty">No lights yet. Add one to start.</p>
  return (
    <section className="desk" data-slot="desk" aria-label="Lighting desk">
      <div className="d-head">
        <b>All lights</b>
        <span>{picks.length > 1 ? `${picks.length} selected` : `${lights.length} ${lights.length === 1 ? 'light' : 'lights'}`}</span>
      </div>
      <div className="d-strips">
        {lights.map((l) => (
          <Strip key={l.id} light={l} picked={picked.has(l.id)} picking={picks.length > 0} group={picks} onToggle={toggle} onOpen={onOpenLight} />
        ))}
      </div>
      <Looks />
      <p className="d-hint">Shift-click or press and hold a light to pick several. Dragging one fader moves them all.</p>
    </section>
  )
}

interface StripProps {
  light: LightView
  picked: boolean
  /** Some strip is picked, so a plain tap picks too (phone, after a long press). */
  picking: boolean
  group: string[]
  onToggle: (id: string) => void
  onOpen: () => void
}

function Strip({ light, picked, picking, group, onToggle, onOpen }: StripProps) {
  const select = useStudio((s) => s.select)
  const applyTo = useStudio((s) => s.applyTo)
  const powerOf = useStudio((s) => s.powerOf)
  const showLevel = useStudio((s) => s.showLevel)
  const { state, caps } = light
  const shown = readout(state, caps)
  const press = useRef<{ timer: number; fired: boolean; x: number; y: number } | null>(null)
  const drag = useRef<Drag | null>(null)
  // The level under the finger while a grouped fader is dragged. The server's copy lags and
  // the Slider drops a move that equals its own value, so it must not decide what the fader shows.
  const [held, setHeld] = useState<number | null>(null)
  const grouped = picked && group.length > 1
  const level = held ?? state.brightness

  useEffect(() => () => {
    if (press.current) window.clearTimeout(press.current.timer)
    // The strip is leaving (a view switch, a refreshed list): send the move still waiting for its frame.
    const d = drag.current
    if (d?.frame) {
      cancelAnimationFrame(d.frame)
      sendMany(d)
    }
  }, [])

  // A drag begins with the first pointer-down or key press on the fader and lasts until the
  // pointer lifts or the fader loses focus. The service scales from the levels at its start.
  const begin = () => {
    if (drag.current || !grouped) return
    const now = useStudio.getState().lights
    const start = Object.fromEntries(group.map((id) => [id, now.find((l) => l.id === id)?.state.brightness ?? 0]))
    drag.current = { anchor: light.id, start, level: null, frame: 0 }
  }
  const end = () => {
    const d = drag.current
    drag.current = null
    if (!d) return
    if (d.frame) {
      cancelAnimationFrame(d.frame)
      sendMany(d)
    }
    if (d.level !== null) {
      // Show every picked light where the service will put it, so a drag started at once reads these
      // levels and not the stale ones the service has not answered for yet.
      for (const [id, next] of Object.entries(scaleLevels(d.start, d.anchor, d.level))) showLevel(id, next)
    }
    setHeld(null)
  }

  const move = (next: number) => {
    if (!grouped) {
      applyTo(light.id, { brightness: next })
      return
    }
    begin()
    const d = drag.current!
    d.level = next
    setHeld(next)
    // One set.many per frame, latest level wins; the service does the scaling.
    if (!d.frame) d.frame = requestAnimationFrame(() => { d.frame = 0; sendMany(d) })
  }

  const down = (e: PointerEvent) => {
    // A new touch ends whatever the last one left behind (a long press whose click never came).
    if (press.current) window.clearTimeout(press.current.timer)
    press.current = null
    if (e.pointerType !== 'touch' || (e.target as Element).closest('.d-fader, button')) return
    const rest = {
      fired: false, x: e.clientX, y: e.clientY,
      timer: window.setTimeout(() => { rest.fired = true; onToggle(light.id) }, LONG_PRESS_MS),
    }
    press.current = rest
  }
  const drift = (e: PointerEvent) => {
    const rest = press.current
    if (rest && !rest.fired && Math.hypot(e.clientX - rest.x, e.clientY - rest.y) > LONG_PRESS_DRIFT) {
      window.clearTimeout(rest.timer)
      press.current = null
    }
  }
  const lift = () => {
    if (press.current && !press.current.fired) {
      window.clearTimeout(press.current.timer)
      press.current = null
    }
  }
  const abandon = () => {
    if (press.current) window.clearTimeout(press.current.timer)
    press.current = null
  }

  return (
    <div
      className={`d-strip ${picked ? 'picked' : ''}`}
      data-light={light.id}
      aria-selected={picked}
      onPointerDown={down}
      onPointerUp={lift}
      onPointerCancel={abandon}
      onPointerMove={drift}
      onClick={(e) => {
        if ((e.target as Element).closest('.d-fader, button')) return
        if (press.current?.fired) {
          press.current = null
          return
        }
        if (e.shiftKey || picking) onToggle(light.id)
      }}
    >
      <div className="d-chip" style={{ '--chip': beamOf(state).css } as CSSProperties} />
      <button
        type="button" className="d-name" title={light.name}
        onClick={() => { select(light.id); onOpen() }}
      >
        {light.name}
      </button>
      <div className="d-model">{modelLine(light)}</div>
      <div className="d-read">{shown.big}{shown.unit && <small>{shown.unit}</small>}</div>
      <div className="d-k">{state.power ? `${Math.round(level)}%` : 'Off'}</div>
      <div
        className="d-fader"
        onPointerDownCapture={begin} onPointerUp={end} onPointerCancel={end} onBlur={end}
      >
        <Slider
          vertical showValue={false} label={`${light.name} brightness`}
          value={level} min={0} max={100} step={1} onChange={move}
        />
      </div>
      <button
        type="button" role="switch" aria-checked={state.power} aria-label={`${light.name} power`}
        className={`d-pw ${state.power ? 'on' : ''}`} onClick={() => powerOf(light.id, !state.power)}
      >
        {state.power ? 'On' : 'Off'}
      </button>
    </div>
  )
}

function Looks() {
  const { looks, apply, allOff } = useDeskLooks()
  const lights = useStudio((s) => s.lights)
  const [last, setLast] = useState<string | null>(null)
  const off = lights.length > 0 && lights.every((l) => !l.state.power)
  return (
    <div className="d-looks">
      {looks.map((look, i) => (
        <button
          key={look.id} type="button" className={`d-look ${last === look.id && !off ? 'on' : ''}`}
          title={look.name} onClick={() => { setLast(look.id); apply(look.id) }}
        >
          <b>{i + 1}</b><span>{look.name}</span>
        </button>
      ))}
      <button type="button" className="d-look" onClick={() => { setLast(null); if (off) allOn(); else allOff() }}>
        <b>0</b><span>{off ? 'All on' : 'All off'}</span>
      </button>
    </div>
  )
}
