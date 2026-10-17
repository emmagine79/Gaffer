import { ArrowRight, Bluetooth, Copy, Power, Settings2 } from 'lucide-react'
import { Key, Panel } from '../../components/Controls'
import { Slider } from '../../components/Slider'
import { emission, hsvToRgb, kelvinToRgb, rgbCss } from '../../lib/color'
import { levelTrack } from '../../lib/tracks'
import type { LightView } from '../../lib/types'
import { useStudio } from '../../state/store'
import { statusOf } from '../../app/LightSwitcher'
import { KIND_SHORT, LightGlyph, formOf } from '../../visuals/LightGlyph'

const HUES = [0, 30, 55, 140, 200, 265, 310]
const WHITES = [2700, 3200, 4300, 5600, 6500]

/** Quick looks this light can actually show: whites in its range, colours if it has colour. */
function QuickLooks({ light }: { light: LightView }) {
  const applyTo = useStudio((s) => s.applyTo)
  const { caps } = light
  const whites = caps.features.white
    ? (caps.features.daylight ? [caps.min_kelvin] : WHITES.filter((k) => k >= caps.min_kelvin && k <= caps.max_kelvin))
    : []
  return (
    <div className="inspector-looks">
      {whites.map((k) => (
        <button key={k} type="button" className="look-dot" title={`${k} K`} style={{ background: rgbCss(kelvinToRgb(k)) }}
          onClick={() => applyTo(light.id, { power: true, mode: 'cct', cct: { kelvin: k } }, { fade: 0.4 })} />
      ))}
      {caps.features.colour && HUES.map((h) => (
        <button key={h} type="button" className="look-dot" title={`Hue ${h}°`} style={{ background: rgbCss(hsvToRgb(h, 100)) }}
          onClick={() => applyTo(light.id, { power: true, mode: 'hsi', hsi: { hue: h, sat: 100 } }, { fade: 0.4 })} />
      ))}
    </div>
  )
}

export function Inspector({ light }: { light: LightView | null }) {
  const linkUp = useStudio((s) => s.link?.status === 'connected')
  const gateway = useStudio((s) => s.link?.gateway)
  const lights = useStudio((s) => s.lights)
  const applyTo = useStudio((s) => s.applyTo)
  const powerOf = useStudio((s) => s.powerOf)
  const send = useStudio((s) => s.send)
  const select = useStudio((s) => s.select)
  const setTab = useStudio((s) => s.setTab)
  const toast = useStudio((s) => s.toast)

  if (!light) {
    return <Panel className="inspector"><p className="muted">Click a light on the plan to control it here.</p></Panel>
  }
  const { rgb, level } = emission(light.state)
  const status = statusOf(light, linkUp)
  const others = lights.filter((l) => l.id !== light.id && l.online)

  return (
    <Panel className="inspector">
      <div className="inspector-head">
        <LightGlyph form={formOf(light.model)} rgb={rgb} level={level} off={!light.state.power} size={64} />
        <div className="inspector-id">
          <h3>{light.name}</h3>
          <p className="muted">{light.model} · {KIND_SHORT[light.kind]}</p>
          <p className="inspector-status"><i className={`dot dot--${status.tone}`} /> {status.text}
            {gateway === light.id && <span className="inspector-gw"><Bluetooth size={11} /> link</span>}</p>
        </div>
        <button type="button" className={`switcher-power inspector-power ${light.state.power ? 'is-on' : ''}`}
          onClick={() => powerOf(light.id, !light.state.power, 0.3)} disabled={!light.online}
          aria-label={light.state.power ? 'Switch off' : 'Switch on'}>
          <Power size={18} strokeWidth={2.4} />
        </button>
      </div>

      {light.online ? (
        <>
          <Slider label={`${light.name} brightness`} value={Math.round(light.state.brightness)} min={0} max={100} step={1}
            track={levelTrack(light.state.power ? rgb : [0.3, 0.3, 0.32])}
            onChange={(v) => applyTo(light.id, { brightness: v, ...(light.state.power ? {} : { power: true }) })}
            format={(v) => `${v}%`} />
          <QuickLooks light={light} />
          <div className="inspector-actions">
            <Key kind="primary" onClick={() => { select(light.id); setTab('live') }}>All controls <ArrowRight /></Key>
            <Key onClick={() => { select(light.id); setTab('device') }}><Settings2 /> Device</Key>
            {others.length > 0 && (
              <Key kind="ghost" title="Give every other light this look once, fitted to each one"
                onClick={() => { send({ type: 'group.match', light: light.id, targets: others.map((o) => o.id), props: ['power', 'brightness', 'white', 'colour'] }); toast(`Copied ${light.name}'s look to ${others.length} more`, 'ok') }}>
                <Copy /> Copy look to all
              </Key>
            )}
          </div>
        </>
      ) : (
        <div className="inspector-away">
          <p className="muted">This light is on a different mesh network than the one the studio is connected to. Choosing it moves the connection over.</p>
          <Key kind="primary" onClick={() => select(light.id, { connect: true })}>Connect to it</Key>
        </div>
      )}
    </Panel>
  )
}
