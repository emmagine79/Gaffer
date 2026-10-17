import type { ReactNode } from 'react'
import { Slider } from '../components/Slider'
import { clamp, hueName } from '../lib/color'
import { hueTrack, kelvinTrack, satTrack } from '../lib/tracks'
import type { LightView } from '../lib/types'
import { useStudio } from '../state/store'
import { Effects } from '../effects/Effects'
import { beamOf, heldBy, modelLine, readout, runningEffect, sentence } from './describe'
import { Lamp } from './Lamp'
import { LookCards } from './LookCards'

/**
 * Glass: one light at a time (design/directions/a-glass.html, design/round4/d-switch.html).
 * Every control comes from the light's model file: colour only when caps.features.colour,
 * colour temperature only when the light has white that is not fixed daylight.
 */
export function Glass() {
  const ready = useStudio((s) => s.ready)
  const light = useStudio((s) => s.light)
  if (!ready) return <p className="g-empty">Opening Gaffer</p>
  return (
    <>
      <LightTabs />
      {light ? <LightPanel light={light} /> : <p className="g-empty">No lights yet. Add one to start.</p>}
      <LookCards />
    </>
  )
}

function LightTabs() {
  const lights = useStudio((s) => s.lights)
  const selected = useStudio((s) => s.selected)
  const select = useStudio((s) => s.select)
  const setAddLight = useStudio((s) => s.setAddLight)
  return (
    <nav className="g-tabs" aria-label="Lights">
      {lights.map((l) => (
        <button
          key={l.id}
          type="button"
          className={`g-tab ${l.id === selected ? 'sel' : ''}`}
          aria-pressed={l.id === selected}
          title={l.name}
          onClick={() => select(l.id)}
        >
          {l.name}
        </button>
      ))}
      <button type="button" className="g-tab" onClick={() => setAddLight(true)}>+ Add</button>
    </nav>
  )
}

function LightPanel({ light }: { light: LightView }) {
  const state = useStudio((s) => s.state) ?? light.state
  const apply = useStudio((s) => s.apply)
  const power = useStudio((s) => s.power)
  const { caps } = light
  const f = caps.features
  const showKelvin = f.white && !f.daylight
  const running = runningEffect(light.engine)
  // A playing effect streams frames in white or colour mode: those frames are not the light's setting.
  const hsi = state.mode === 'hsi' && f.colour && !running
  const shown = readout(state, caps, running)
  const held = heldBy(state, caps, running)
  return (
    <div className="g-light" data-light={light.id}>
      <div className="g-row">
        <div className="g-who">
          <h1 className="g-name">{light.name}</h1>
          <p className="g-model">{modelLine(light)}</p>
        </div>
        <button
          type="button"
          role="switch"
          className={`g-toggle ${state.power ? 'on' : ''}`}
          aria-checked={state.power}
          aria-label={`${light.name} power`}
          onClick={() => power(!state.power)}
        />
      </div>
      <div className="g-hero">
        <span className="g-big">{shown.big}</span>
        {shown.unit && <span className="g-unit">{shown.unit}</span>}
      </div>
      <p className="g-sub">{sentence(state, caps, running)}</p>
      <Lamp level={beamOf(state).level} />

      <Control label="Brightness" aside={`${Math.round(state.brightness)}%`}>
        <Stepper
          className="g-bright" label="Brightness" value={state.brightness} min={0} max={100} step={1} jump={5}
          onChange={(v) => apply({ brightness: v })}
        />
      </Control>

      {showKelvin && (held ? (
        <Control label="Colour temperature" aside="Not in use">
          <button type="button" className="g-back" onClick={() => apply({ mode: 'cct' })}>Back to white</button>
        </Control>
      ) : (
        <Control label="Colour temperature" aside={`${caps.min_kelvin}K to ${caps.max_kelvin}K`}>
          <Stepper
            className="g-knob" label="Colour temperature" value={state.cct.kelvin}
            min={caps.min_kelvin} max={caps.max_kelvin} step={50} jump={100}
            track={kelvinTrack(caps.min_kelvin, caps.max_kelvin, 6)}
            onChange={(v) => apply({ mode: 'cct', cct: { kelvin: Math.round(v) } })}
          />
        </Control>
      ))}
      {f.daylight && (
        <Control label="Colour temperature" aside={`Fixed ${caps.min_kelvin}K daylight`} />
      )}

      {f.colour && (
        <div className="g-colour" data-control="colour">
          <Control label="Colour" aside={running ? 'Not in use' : hsi ? capital(hueName(state.hsi.hue)) : held ?? 'White'}>
            {!running && (
              <Stepper
                className="g-knob" label="Hue" value={state.hsi.hue} min={0} max={359} step={1} jump={10}
                track={hueTrack()}
                onChange={(v) => apply({ mode: 'hsi', hsi: { hue: v, sat: state.hsi.sat || 100 } })}
              />
            )}
          </Control>
          {hsi && (
            <Control label="Saturation" aside={`${Math.round(state.hsi.sat)}%`}>
              <Stepper
                className="g-knob" label="Saturation" value={state.hsi.sat} min={0} max={100} step={1} jump={5}
                track={satTrack(state.hsi.hue)}
                onChange={(v) => apply({ mode: 'hsi', hsi: { sat: v } })}
              />
            </Control>
          )}
        </div>
      )}

      <Effects light={light} />
    </div>
  )
}

const capital = (word: string) => word.charAt(0).toUpperCase() + word.slice(1)

function Control({ label, aside, children }: { label: string; aside: string; children?: ReactNode }) {
  return (
    <div className="g-ctl">
      <div className="g-lab"><span>{label}</span><span>{aside}</span></div>
      {children}
    </div>
  )
}

interface StepperProps {
  label: string
  value: number
  min: number
  max: number
  step: number
  /** How far one press of − or + moves. */
  jump: number
  onChange: (value: number) => void
  track?: string
  className?: string
}

/** lumen's Slider between − and + buttons, styled as the mockup's track. */
function Stepper({ label, value, min, max, step, jump, onChange, track, className = '' }: StepperProps) {
  const nudge = (by: number) => onChange(clamp(Math.round((value + by) / step) * step, min, max))
  return (
    <div className={`g-slider ${className}`}>
      <button type="button" className="g-pm" aria-label={`Less ${label.toLowerCase()}`} onClick={() => nudge(-jump)}>−</button>
      <Slider label={label} value={value} min={min} max={max} step={step} track={track} showValue={false} onChange={onChange} />
      <button type="button" className="g-pm" aria-label={`More ${label.toLowerCase()}`} onClick={() => nudge(jump)}>+</button>
    </div>
  )
}
