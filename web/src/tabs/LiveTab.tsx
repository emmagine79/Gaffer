import { BookmarkPlus, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Key, Panel, Segmented } from '../components/Controls'
import { InlineSave } from '../components/InlineSave'
import { hsvToRgb, kelvinToRgb, rgbCss } from '../lib/color'
import type { Caps, LightState, StatePatch } from '../lib/types'
import { useStudio } from '../state/store'
import { describe } from '../app/describe'
import { emission } from '../lib/color'
import { useHistory } from '../state/history'
import { SUBJECTS } from '../visuals/scenes'
import { StudioSet } from '../visuals/StudioSet'
import './tabs.css'

interface Look { name: string; patch: StatePatch; swatch: string }

const LOOKS: Look[] = [
  { name: 'Daylight', patch: { mode: 'cct', brightness: 70, cct: { kelvin: 5600, gm: 0 } }, swatch: rgbCss(kelvinToRgb(5600)) },
  { name: 'Tungsten', patch: { mode: 'cct', brightness: 60, cct: { kelvin: 3200, gm: 0 } }, swatch: rgbCss(kelvinToRgb(3200)) },
  { name: 'Golden hour', patch: { mode: 'cct', brightness: 62, cct: { kelvin: 2700, gm: 12 } }, swatch: rgbCss(kelvinToRgb(2700)) },
  { name: 'Candlelight', patch: { mode: 'cct', brightness: 30, cct: { kelvin: 1800, gm: 0 } }, swatch: rgbCss(kelvinToRgb(1800)) },
  { name: 'Overcast', patch: { mode: 'cct', brightness: 55, cct: { kelvin: 6500, gm: -6 } }, swatch: rgbCss(kelvinToRgb(6500)) },
  { name: 'Moonlight', patch: { mode: 'cct', brightness: 18, cct: { kelvin: 9000, gm: 0 } }, swatch: rgbCss(kelvinToRgb(9000)) },
  { name: 'Blue hour', patch: { mode: 'hsi', brightness: 40, hsi: { hue: 222, sat: 72 } }, swatch: rgbCss(hsvToRgb(222, 72)) },
  { name: 'Sodium street', patch: { mode: 'hsi', brightness: 45, hsi: { hue: 30, sat: 96 } }, swatch: rgbCss(hsvToRgb(30, 96)) },
  { name: 'Neon pink', patch: { mode: 'hsi', brightness: 70, hsi: { hue: 322, sat: 100 } }, swatch: rgbCss(hsvToRgb(322, 100)) },
  { name: 'Cyber cyan', patch: { mode: 'hsi', brightness: 60, hsi: { hue: 188, sat: 100 } }, swatch: rgbCss(hsvToRgb(188, 100)) },
  { name: 'Darkroom', patch: { mode: 'hsi', brightness: 12, hsi: { hue: 0, sat: 100 } }, swatch: rgbCss(hsvToRgb(0, 100)) },
  { name: 'Emerald', patch: { mode: 'hsi', brightness: 55, hsi: { hue: 145, sat: 90 } }, swatch: rgbCss(hsvToRgb(145, 90)) },
]

/** Levels for a light whose only control is brightness. */
const LEVELS: Look[] = [
  { name: 'Full', patch: { brightness: 100 }, swatch: rgbCss(kelvinToRgb(5600)) },
  { name: 'Bright', patch: { brightness: 75 }, swatch: rgbCss(kelvinToRgb(5600)) },
  { name: 'Half', patch: { brightness: 50 }, swatch: 'rgb(190 190 186)' },
  { name: 'Low', patch: { brightness: 20 }, swatch: 'rgb(120 120 118)' },
  { name: 'Night light', patch: { brightness: 5 }, swatch: 'rgb(70 70 69)' },
]

/**
 * The quick looks for this light: colours only if it has colour, and each white
 * fitted to its range, so "Candlelight" on a 2800 K light is its warmest dim white.
 */
function looksFor(caps: Caps | null): Look[] {
  if (!caps) return LOOKS
  if (caps.features.daylight) return LEVELS
  return LOOKS.flatMap((l) => {
    if (l.patch.mode === 'hsi') return caps.features.colour ? [l] : []
    if (!caps.features.white || !l.patch.cct) return []
    const kelvin = Math.max(caps.min_kelvin, Math.min(caps.max_kelvin, l.patch.cct.kelvin ?? 5600))
    const gm = caps.features.tint ? l.patch.cct.gm ?? 0 : 0
    return [{ ...l, patch: { ...l.patch, cct: { kelvin, gm } }, swatch: rgbCss(kelvinToRgb(kelvin)) }]
  })
}

function ago(ts: number | null | undefined) {
  if (!ts) return 'not yet'
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts))
  return s < 2 ? 'just now' : `${s}s ago`
}

function inSync(s: LightState, rb: ReturnType<typeof useStudio.getState>['readback']): boolean | null {
  if (!rb || !s.power) return null
  if (s.mode === 'cct' && rb.cct) {
    return Math.round(s.brightness) === rb.cct.brightness && Math.round(s.cct.kelvin / 100) * 100 === rb.cct.kelvin && s.cct.gm === rb.cct.gm
  }
  if (s.mode === 'hsi' && rb.hsi) {
    return Math.round(s.brightness) === rb.hsi.brightness && Math.round(s.hsi.hue) % 360 === rb.hsi.hue % 360 && Math.round(s.hsi.sat) === rb.hsi.sat
  }
  return null
}

export function LiveTab() {
  const apply = useStudio((s) => s.apply)
  const state = useStudio((s) => s.state)
  const readback = useStudio((s) => s.readback)
  const engine = useStudio((s) => s.engine)
  const send = useStudio((s) => s.send)
  const upsert = useStudio((s) => s.upsert)
  const toast = useStudio((s) => s.toast)
  const [subject, setSubject] = useState(() => localStorage.getItem('lumen.subject') ?? 'bookshelf')
  const [fade, setFade] = useState(0.6)
  const [, tick] = useState(0)
  const recent = useHistory((s) => s.looks)
  const caps = useStudio((s) => s.caps)
  const effects = useStudio((s) => s.effects)

  useEffect(() => {
    try { localStorage.setItem('lumen.subject', subject) } catch { /* private mode */ }
  }, [subject])
  useEffect(() => {
    const t = window.setInterval(() => tick((n) => n + 1), 1000)
    return () => window.clearInterval(t)
  }, [])

  if (!state) return null
  const synced = engine.kind ? null : inSync(state, readback)

  const snapshot = async (name: string) => {
    const item = await upsert('scenes', { name })
    if (item) toast(`Saved "${item.name}" to Scenes`, 'ok')
  }

  return (
    <div className="live">
      <div className="live-set">
        <StudioSet subject={subject} className="live-set-svg" />
        <div className="live-set-bar">
          <Segmented label="Subject" size="sm" value={subject} onChange={setSubject}
            options={SUBJECTS.map((s) => ({ value: s.id, label: s.name }))} />
          <InlineSave label="Save this look" icon={<BookmarkPlus />} placeholder="Name this look" onSave={snapshot} />
        </div>
      </div>

      <Panel title="Recent looks" className="live-recent" aside={<span>Click to go back</span>}>
        {recent.length === 0 ? (
          <p className="muted">Looks you settle on appear here, newest first, so you can always step back.</p>
        ) : (
          <div className="recent-row">
            {recent.map((look, i) => {
              const { rgb } = emission(look)
              const text = describe(look, engine.kind ? { ...engine, kind: null } : engine, caps, effects)
              return (
                <button key={i} type="button" className="recent" onClick={() => send({ type: 'look.apply', patch: look, fade: 0.6 })} title={`${text.title}: ${text.detail}`}>
                  <span className="recent-swatch" style={{ background: rgbCss(rgb), opacity: 0.35 + (look.brightness / 100) * 0.65 }} />
                  <span className="recent-name">{text.title}</span>
                  <span className="recent-level">{Math.round(look.brightness)}%</span>
                </button>
              )
            })}
          </div>
        )}
      </Panel>

      <div className="live-side">
        <Panel title="Quick looks" aside={
          <Segmented label="Fade" size="sm" value={fade} onChange={setFade}
            options={[{ value: 0, label: 'Cut' }, { value: 0.6, label: '0.6s' }, { value: 2, label: '2s' }, { value: 5, label: '5s' }]} />
        }>
          <div className="looks">
            {looksFor(caps).map((l) => (
              <button key={l.name} type="button" className="look" onClick={() => apply({ power: true, ...l.patch }, { fade })}>
                <span className="look-swatch" style={{ background: l.swatch }} />
                <span>{l.name}</span>
              </button>
            ))}
          </div>
        </Panel>

        <Panel title="What the light reports" aside={
          <Key kind="ghost" onClick={() => send({ type: 'readback' })} title="Ask the light now"><RefreshCw /> Read</Key>
        }>
          <div className={`sync-badge ${synced === true ? 'is-ok' : synced === false ? 'is-off' : ''}`}>
            {synced === true && 'In sync: the light confirms what you see'}
            {synced === false && 'Catching up: the light has not confirmed the latest change yet'}
            {synced === null && (engine.kind ? 'An effect is driving the light; it is the source of truth' : 'This mode cannot be read back; showing what was sent')}
          </div>
          <dl className="facts">
            <div><dt>White record</dt><dd>{readback?.cct ? `${readback.cct.brightness}%  ${readback.cct.kelvin} K  tint ${readback.cct.gm}` : 'none yet'}</dd></div>
            {caps?.features.colour && <div><dt>Colour record</dt><dd>{readback?.hsi ? `${readback.hsi.brightness}%  hue ${readback.hsi.hue}°  sat ${readback.hsi.sat}%` : 'none yet'}</dd></div>}
            <div><dt>Round trip</dt><dd>{readback?.latency_ms != null ? `${Math.round(readback.latency_ms)} ms` : 'not measured'}</dd></div>
            <div><dt>Heartbeat</dt><dd>{ago(readback?.heartbeat_at)}</dd></div>
          </dl>
        </Panel>
      </div>
    </div>
  )
}
