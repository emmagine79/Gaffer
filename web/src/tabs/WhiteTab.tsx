import { Minus, Plus, Sun } from 'lucide-react'
import { Key, Panel } from '../components/Controls'
import { Slider } from '../components/Slider'
import { kelvinName, kelvinToRgb, rgbCss } from '../lib/color'
import { kelvinTrack, levelTrack, tintTrack } from '../lib/tracks'
import { useStudio } from '../state/store'
import './tabs.css'

const PRESETS = [
  { k: 1800, name: 'Candle' }, { k: 2400, name: 'Sunrise' }, { k: 2700, name: 'Warm home' },
  { k: 3200, name: 'Tungsten' }, { k: 3400, name: 'Halogen' }, { k: 4300, name: 'Fluorescent' },
  { k: 5000, name: 'Noon' }, { k: 5600, name: 'Daylight' }, { k: 6500, name: 'Overcast' },
  { k: 7500, name: 'Open shade' }, { k: 10000, name: 'Blue sky' },
]

function tintLabel(gm: number) {
  if (gm === 0) return 'Neutral'
  return gm > 0 ? `+${gm} magenta` : `${gm} green`
}

export function WhiteTab() {
  const state = useStudio((s) => s.state)
  const caps = useStudio((s) => s.caps)
  const apply = useStudio((s) => s.apply)
  if (!state || !caps) return null

  const active = state.mode === 'cct'
  const kelvin = state.cct.kelvin
  const min = caps.min_kelvin
  const max = caps.max_kelvin
  const daylight = caps.features.daylight
  const setKelvin = (k: number) => apply({ power: true, mode: 'cct', cct: { kelvin: Math.max(min, Math.min(max, k)) } })

  if (daylight) {
    return (
      <div className="white">
        <Panel className="white-hero">
          <div className="white-readout">
            <div>
              <p className="white-name">{kelvinName(min)}{!active && <span className="badge">not active: the light is in {state.mode.toUpperCase()} mode</span>}</p>
              <p className="readout white-k">{min}<small>K</small></p>
            </div>
            <div className="white-steps">{!active && <Key kind="primary" onClick={() => setKelvin(min)}>Use white</Key>}</div>
          </div>
          <div className="adapt-note">
            <Sun size={16} />
            <p>The <b>{caps.name}</b> is a daylight light: one colour temperature, {min} K. Brightness is its control, on the master fader below and in fine steps here.</p>
          </div>
        </Panel>
        <FineDimming />
      </div>
    )
  }

  return (
    <div className="white">
      <Panel className="white-hero">
        <div className="white-readout">
          <div>
            <p className="white-name">{kelvinName(kelvin)}{!active && <span className="badge">not active: the light is in {state.mode.toUpperCase()} mode</span>}</p>
            <p className="readout white-k">{kelvin}<small>K</small></p>
          </div>
          <div className="white-steps">
            <Key onClick={() => setKelvin(kelvin - 100)} title="100 K warmer"><Minus /> 100 K</Key>
            <Key onClick={() => setKelvin(kelvin + 100)} title="100 K cooler"><Plus /> 100 K</Key>
            {!active && <Key kind="primary" onClick={() => setKelvin(kelvin)}>Use white</Key>}
          </div>
        </div>
        <Slider
          className="slider--strip"
          label="Colour temperature"
          value={kelvin}
          min={min}
          max={max}
          step={50}
          track={kelvinTrack(min, max, 24)}
          ticks={[2000, 3200, 4300, 5600, 6500, 8000].filter((t) => t > min && t < max)}
          onChange={setKelvin}
          format={(v) => `${v} K`}
          showValue={false}
        />
        <div className="strip-scale" aria-hidden="true">
          <span>{min} K, warmer</span>
          <span>cooler, {max} K</span>
        </div>
      </Panel>

      <div className="white-grid">
        <Panel title="Presets">
          <div className="kelvin-chips">
            {PRESETS.filter((p) => p.k >= min && p.k <= max).map((p) => (
              <button
                key={p.k}
                type="button"
                className={`kelvin-chip ${active && kelvin === p.k ? 'is-on' : ''}`}
                onClick={() => apply({ power: true, mode: 'cct', cct: { kelvin: p.k } }, { fade: 0.5 })}
              >
                <span className="kelvin-chip-swatch" style={{ background: rgbCss(kelvinToRgb(p.k)) }} />
                <span className="kelvin-chip-k">{p.k} K</span>
                <span className="kelvin-chip-name">{p.name}</span>
              </button>
            ))}
          </div>
        </Panel>

        <div className="stack">
          {caps.has_tint && (
            <Panel title="Tint" aside={<span>{tintLabel(state.cct.gm)}</span>}>
              <>
                <Slider
                  label="Green to magenta tint"
                  value={state.cct.gm}
                  min={caps.gm_min}
                  max={caps.gm_max}
                  step={1}
                  track={tintTrack}
                  ticks={[0]}
                  onChange={(gm) => apply({ power: true, mode: 'cct', cct: { gm: Math.abs(gm) <= 2 ? 0 : gm } })}
                  format={(v) => (v > 0 ? `+${v}` : `${v}`)}
                />
                <p className="hint">Pull toward green to match fluorescent or LED practicals, toward magenta to warm skin. Snaps to neutral near the centre.</p>
              </>
            </Panel>
          )}
          <FineDimming />
        </div>
      </div>
    </div>
  )
}

function FineDimming() {
  const state = useStudio((s) => s.state)
  const apply = useStudio((s) => s.apply)
  if (!state) return null
  const kelvin = state.cct.kelvin
  return (
          <Panel title="Fine dimming" aside={<span>{state.brightness.toFixed(1)}%</span>}>
            <Slider
              label="Fine brightness, 0 to 10 percent"
              value={Math.min(10, state.brightness)}
              min={0}
              max={10}
              step={0.1}
              track={levelTrack(kelvinToRgb(kelvin))}
              onChange={(b) => apply({ power: true, brightness: b })}
              format={(v) => `${v.toFixed(1)}%`}
            />
            <p className="hint">Tenth-of-a-percent steps for the bottom of the range, where the eye is most sensitive. The light takes 0.1% resolution; most apps only send whole percents.</p>
          </Panel>
  )
}
