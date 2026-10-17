import { Bluetooth, BluetoothSearching, Power, Square } from 'lucide-react'
import { emission, rgbCss } from '../lib/color'
import { levelTrack } from '../lib/tracks'
import { Slider } from '../components/Slider'
import { useStudio } from '../state/store'
import { describe } from './describe'
import './shell.css'

export function SignalBars({ rssi }: { rssi: number | null }) {
  const bars = rssi === null ? 0 : rssi > -55 ? 4 : rssi > -65 ? 3 : rssi > -75 ? 2 : 1
  return (
    <span className="signal" aria-label={rssi === null ? 'No signal' : `Signal ${rssi} dBm`}>
      {[1, 2, 3, 4].map((b) => <i key={b} className={b <= bars ? 'is-on' : ''} style={{ height: 3 + b * 3 }} />)}
    </span>
  )
}

export function linkLabel(status: string | undefined, socketOpen: boolean) {
  if (!socketOpen) return 'Studio offline'
  switch (status) {
    case 'connected': return 'Connected'
    case 'scanning': return 'Looking for your lights'
    case 'no-light': return 'No lights yet'
    case 'connecting': return 'Connecting'
    case 'backoff': return 'Retrying'
    default: return 'Not connected'
  }
}

export function MasterBar() {
  const state = useStudio((s) => s.state)
  const engine = useStudio((s) => s.engine)
  const caps = useStudio((s) => s.caps)
  const effects = useStudio((s) => s.effects)
  const link = useStudio((s) => s.link)
  const socketOpen = useStudio((s) => s.socketOpen)
  const apply = useStudio((s) => s.apply)
  const power = useStudio((s) => s.power)
  const send = useStudio((s) => s.send)
  const setSheet = useStudio((s) => s.setConnectionSheet)
  const light = useStudio((s) => s.light)
  const many = useStudio((s) => s.lights.length > 1)

  if (!state || !light) return <footer className="master" />
  const battery = light.device.battery?.percent
  const { rgb } = emission(state)
  const { title, detail } = describe(state, engine, caps, effects)
  const connected = socketOpen && link?.status === 'connected'
  const live = engine.kind === 'effect' || engine.kind === 'timeline' || engine.kind === 'stream'

  return (
    <footer className="master" aria-label="Master controls">
      <button
        type="button"
        className={`master-power ${state.power ? 'is-on' : ''}`}
        onClick={() => power(!state.power, 0.4)}
        aria-pressed={state.power}
        title={state.power ? 'Switch off (Space)' : 'Switch on (Space)'}
      >
        <Power strokeWidth={2.4} />
        <span className="sr-only">{state.power ? 'Switch off' : 'Switch on'}</span>
      </button>

      <div className="master-now">
        <span className="master-swatch" style={{ background: state.power ? rgbCss(rgb) : '#2b2c30' }}>
          {live && <span className="tally" title="An effect is driving the light" />}
        </span>
        <span className="master-now-text">
          {many && <span className="master-light">{light.name}</span>}
          <strong>{title}</strong>
          <span className="muted">{detail}{battery != null ? ` · battery ${battery}%` : ''}</span>
        </span>
        {engine.kind && engine.kind !== 'transition' && (
          <button type="button" className="master-stop" onClick={() => send({ type: 'engine.stop' })} title="Stop (Esc)">
            <Square size={13} fill="currentColor" />
            <span>Stop</span>
          </button>
        )}
      </div>

      <div className="master-fader">
        <Slider
          label="Master brightness"
          value={Math.round(state.brightness * 10) / 10}
          min={0}
          max={100}
          step={1}
          ticks={[25, 50, 75]}
          track={levelTrack(state.power ? rgb : [0.3, 0.3, 0.32])}
          onChange={(v) => apply({ brightness: v, ...(state.power ? {} : { power: true }) })}
          showValue={false}
        />
        <output className="master-level readout" aria-live="off">
          {Math.round(state.brightness)}<small>%</small>
        </output>
      </div>

      <button type="button" className={`master-link ${connected ? 'is-ok' : ''}`} onClick={() => setSheet(true)}
        title="Connection details">
        {connected ? <Bluetooth size={18} /> : <BluetoothSearching size={18} className="spin-slow" />}
        <span className="master-link-text">{linkLabel(link?.status, socketOpen)}</span>
        <SignalBars rssi={connected ? link?.rssi ?? null : null} />
      </button>
    </footer>
  )
}
