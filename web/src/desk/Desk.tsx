import { useEffect, useRef, useState, type CSSProperties, type PointerEvent } from 'react'
import { Slider } from '../components/Slider'
import type { LightView } from '../lib/types'
import { beamOf, modelLine, readout } from '../glass/describe'
import { useStudio } from '../state/store'
import { useDeskLooks } from './looks'
import './desk.css'

/** How long a finger rests on a strip before it counts as a selection (phone). */
const LONG_PRESS_MS = 500

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
  const send = useStudio((s) => s.send)
  const { state, caps } = light
  const shown = readout(state, caps)
  const press = useRef<{ timer: number; fired: boolean } | null>(null)
  const frame = useRef<{ id: number; level: number } | null>(null)

  useEffect(() => () => {
    if (press.current) window.clearTimeout(press.current.timer)
    if (frame.current) cancelAnimationFrame(frame.current.id)
  }, [])

  const move = (level: number) => {
    if (!picked || group.length < 2) {
      applyTo(light.id, { brightness: level })
      return
    }
    // One set.many per frame, latest level wins; the service does the scaling.
    if (frame.current) {
      frame.current.level = level
      return
    }
    const job = { id: 0, level }
    job.id = requestAnimationFrame(() => {
      frame.current = null
      send({ type: 'set.many', anchor: light.id, lights: group, brightness: job.level })
    })
    frame.current = job
  }

  const down = (e: PointerEvent) => {
    if (e.pointerType !== 'touch' || (e.target as Element).closest('.d-fader, button')) return
    const held = { fired: false, timer: window.setTimeout(() => { held.fired = true; onToggle(light.id) }, LONG_PRESS_MS) }
    press.current = held
  }
  const cancel = () => {
    if (press.current) window.clearTimeout(press.current.timer)
  }

  return (
    <div
      className={`d-strip ${picked ? 'picked' : ''}`}
      data-light={light.id}
      aria-selected={picked}
      onPointerDown={down}
      onPointerUp={cancel}
      onPointerCancel={cancel}
      onPointerMove={cancel}
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
      <div className="d-k">{state.power ? `${Math.round(state.brightness)}%` : 'Off'}</div>
      <div className="d-fader">
        <Slider
          vertical showValue={false} label={`${light.name} brightness`}
          value={state.brightness} min={0} max={100} step={1} onChange={move}
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
  const off = lights.every((l) => !l.state.power)
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
      <button type="button" className={`d-look ${off ? 'on' : ''}`} onClick={() => { setLast(null); allOff() }}>
        <b>0</b><span>All off</span>
      </button>
    </div>
  )
}
