import { AnimatePresence } from 'motion/react'
import { BatteryCharging, BatteryFull, BatteryLow, BatteryMedium, Fan, Gauge, Pencil, RefreshCw, ScrollText, SlidersHorizontal } from 'lucide-react'
import { useState } from 'react'
import { Field, Key, Panel, Segmented } from '../components/Controls'
import { Slider } from '../components/Slider'
import { SignalBars } from '../app/MasterBar'
import type { Battery } from '../lib/types'
import { useStudio } from '../state/store'
import { KIND_SHORT, LightGlyph, formOf } from '../visuals/LightGlyph'
import { emission } from '../lib/color'
import { ModelDialog } from './mesh/LightsTable'
import './mesh/mesh.css'
import './tabs.css'

const SYNC_SPEEDS = [
  { value: 0, label: 'Off' }, { value: 3, label: 'Relaxed' }, { value: 0.7, label: 'Normal' }, { value: 0.35, label: 'Fast' },
]

function fmtSince(ts: number | null | undefined) {
  if (!ts) return 'not connected'
  const s = Math.round(Date.now() / 1000 - ts)
  if (s < 60) return `${s} s`
  if (s < 3600) return `${Math.floor(s / 60)} min`
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`
}

function BatteryReadout({ battery }: { battery: Battery | null }) {
  if (!battery) return <p className="muted">Reading the battery...</p>
  if (battery.percent == null) return <p className="muted">The light did not report a battery level; it may be on mains power.</p>
  const Icon = battery.state ? BatteryCharging : battery.percent > 70 ? BatteryFull : battery.percent > 30 ? BatteryMedium : BatteryLow
  return (
    <div className="battery">
      <Icon size={30} className={battery.percent <= 20 ? 'battery-low' : ''} />
      <p className="readout battery-pct">{battery.percent}<small>%</small></p>
      {battery.hours != null && <p className="muted">about {battery.hours} h {battery.minutes ?? 0} min left at this level</p>}
    </div>
  )
}

function LightIdentity({ onModel }: { onModel: () => void }) {
  const light = useStudio((s) => s.light)
  const send = useStudio((s) => s.send)
  const [name, setName] = useState(light?.name ?? '')
  if (!light) return null
  const caps = light.caps
  const look = emission(light.state)
  return (
    <Panel className="device-light">
      <div className="device-light-head">
        <LightGlyph form={formOf(light.model)} rgb={look.rgb} level={look.level} off={!light.state.power} size={76} />
        <div className="device-light-id">
          <label className="lt-name device-name">
            <input className="lt-input" value={name} onChange={(e) => setName(e.target.value)} aria-label="Light name"
              onBlur={() => name.trim() && name !== light.name && send({ type: 'lights.rename', light: light.id, name })}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
            <Pencil size={13} />
          </label>
          <p className="muted">{caps.known ? `${caps.name}, ${caps.kind_label}` : 'Model not recognised'} · {light.model_source === 'manual' ? 'model set by you' : light.known_model ? 'recognised from the light' : 'pick its model for the right controls'}</p>
        </div>
        <Key onClick={onModel}>Change model</Key>
      </div>
      <dl className="facts facts--grid">
        <div><dt>Kind</dt><dd>{KIND_SHORT[caps.kind]}</dd></div>
        <div><dt>White</dt><dd>{caps.features.white ? (caps.features.daylight ? `${caps.min_kelvin} K fixed` : `${caps.min_kelvin}-${caps.max_kelvin} K${caps.features.tint ? ', with tint' : ''}`) : 'none'}</dd></div>
        <div><dt>Colour</dt><dd>{caps.features.colour ? (caps.features.channels ? 'HSI and RGBW channels' : 'HSI') : 'none'}</dd></div>
        <div><dt>Gels</dt><dd>{caps.features.gels === 'native' ? 'built in' : caps.features.gels === 'emulated' ? 'recreated from colour' : caps.features.gels === 'white' ? 'correction gels, as white' : 'none'}</dd></div>
        <div><dt>Built-in effects</dt><dd>{caps.effects.length || 'none'}</dd></div>
        <div><dt>Address</dt><dd>{light.address} · node 0x{light.node_address.toString(16).padStart(4, '0')}</dd></div>
      </dl>
      {caps.note && <p className="hint">{caps.note}</p>}
    </Panel>
  )
}

export function DeviceTab() {
  const light = useStudio((s) => s.light)
  const lights = useStudio((s) => s.lights)
  const link = useStudio((s) => s.link)
  const pump = useStudio((s) => s.pump)
  const settings = useStudio((s) => s.store?.settings)
  const log = useStudio((s) => s.log)
  const send = useStudio((s) => s.send)
  const [modelOpen, setModelOpen] = useState(false)
  if (!settings) return null

  const setSetting = (patch: Record<string, unknown>) => send({ type: 'settings', patch })
  const budget = link?.sequence_budget ?? 0
  const connected = link?.status === 'connected'
  const gatewayName = lights.find((l) => l.id === link?.gateway)?.name
  const caps = light?.caps ?? null
  const device = light?.device

  return (
    <div className="device">
      {light && <LightIdentity key={`${light.id}:${light.name}`} onModel={() => setModelOpen(true)} />}

      <div className="device-grid">
        {caps?.features.battery && (
          <Panel title="Battery" aside={<BatteryFull size={16} />}>
            <BatteryReadout battery={device?.battery ?? null} />
          </Panel>
        )}

        {caps?.features.fan && (
          <Panel title="Cooling fan" aside={<Fan size={16} />}>
            <Segmented label="Fan mode" value={device?.fan ?? -1} onChange={(mode) => send({ type: 'fan', mode })}
              options={caps.fan_modes.map((f) => ({ value: f.code, label: f.name }))} />
            <p className="hint">The light never reports its fan mode, so this shows what was last sent.</p>
          </Panel>
        )}

        {caps && (caps.features.smoothness || caps.features.control_modes) && (
          <Panel title="Output" aside={<SlidersHorizontal size={16} />}>
            {caps.features.smoothness && (
              <Field label="Dimming" hint="Smooth ramps between levels; Off steps instantly, which effects and sync prefer">
                <Segmented size="sm" label="Dimming smoothness" value={device?.smoothness ?? -1}
                  onChange={(mode) => send({ type: 'device.smoothness', mode })}
                  options={caps.smoothness_modes.map((o) => ({ value: o.code, label: o.name }))} />
              </Field>
            )}
            {caps.features.control_modes && (
              <Field label="Output mode" hint="Godox's profiles for different uses; frequency tunes the dimming so it does not band on camera">
                <Segmented size="sm" label="Output mode" value={device?.control?.mode ?? -1}
                  onChange={(mode) => send({ type: 'device.control', mode, frequency: device?.control?.frequency ?? caps.frequencies[0]?.code ?? 0 })}
                  options={caps.control_modes.map((o) => ({ value: o.code, label: o.name }))} />
                {caps.frequencies.length > 0 && (
                  <Segmented size="sm" label="Frequency" value={device?.control?.frequency ?? -1}
                    onChange={(frequency) => send({ type: 'device.control', mode: device?.control?.mode ?? caps.control_modes[0]?.code ?? 0, frequency })}
                    options={caps.frequencies.map((o) => ({ value: o.code, label: o.name }))} />
                )}
              </Field>
            )}
          </Panel>
        )}

        <Panel title="Connection" aside={<Key kind="ghost" onClick={() => send({ type: 'link.reconnect' })}><RefreshCw /> Reconnect</Key>}>
          <div className="device-hero">
            <span className={`device-dot ${connected ? 'is-ok' : ''}`} />
            <div>
              <p className="device-status">{connected ? `Linked through ${gatewayName ?? link?.address}` : link?.detail || 'Not connected'}</p>
              <p className="muted">{lights.filter((l) => l.online).length > 1 ? 'The other lights are reached by relay through it' : link?.address}{link?.demo ? ' (simulated)' : ''}</p>
            </div>
            <span className="device-signal"><SignalBars rssi={connected ? link?.rssi ?? null : null} /> {link?.rssi != null ? `${link.rssi} dBm` : ''}</span>
          </div>
          <dl className="facts facts--grid">
            <div><dt>Linked for</dt><dd>{fmtSince(link?.connected_since)}</dd></div>
            <div><dt>Radio interval</dt><dd>{link?.interval_ms != null ? `${link.interval_ms} ms` : 'default'}</dd></div>
            <div><dt>Round trip</dt><dd>{light?.readback.latency_ms != null ? `${Math.round(light.readback.latency_ms)} ms` : 'not measured'}</dd></div>
            <div><dt>Firmware</dt><dd>{link?.firmware?.mcu ? `MCU ${link.firmware.mcu}, mesh ${link.firmware.mesh}` : 'unknown'}</dd></div>
            <div><dt>Mesh source</dt><dd>{link?.source != null ? `0x${link.source.toString(16).padStart(4, '0')}` : 'unknown'}</dd></div>
          </dl>
        </Panel>

        <Panel title="Speed" aside={<Gauge size={16} />}>
          <Field label="Command rate" hint={settings.max_rate > 40 ? 'Turbo: an ML100R took 80 a second cleanly, at the cost of sequence numbers. Shared by every light.' : 'Updates per second during effects and fades, shared by every light'}>
            <Slider label="Command rate" value={settings.max_rate} min={10} max={80} step={5} ticks={[40]} onChange={(v) => setSetting({ max_rate: v })} format={(v) => `${v}/s`} />
          </Field>
          <Field label="Relay hops" hint="How far a command may travel through other lights to reach one out of range. The connected light itself is always reached directly.">
            <Slider label="Relay hops" value={settings.relay_ttl} min={2} max={10} step={1} onChange={(v) => setSetting({ relay_ttl: v })} format={(v) => `${v}`} />
          </Field>
          <Field label="Watch for changes on the light" hint="How often the studio asks the light being edited what it is doing while this page is open">
            <Segmented size="sm" label="Sync speed" value={settings.sync_interval} onChange={(v) => setSetting({ sync_interval: v })} options={SYNC_SPEEDS} />
          </Field>
          <Field label="Default scene fade">
            <Slider label="Default fade" value={settings.default_fade} min={0} max={10} step={0.1} onChange={(v) => setSetting({ default_fade: v })} format={(v) => `${v.toFixed(1)} s`} />
          </Field>
        </Panel>

        <Panel title="Traffic">
          <dl className="facts facts--grid">
            <div><dt>Sending now</dt><dd>{pump ? `${pump.rate}/s` : '0/s'}</dd></div>
            <div><dt>Commands sent</dt><dd>{pump?.sent.toLocaleString() ?? 0}</dd></div>
            <div><dt>Merged before sending</dt><dd>{pump?.coalesced.toLocaleString() ?? 0}</dd></div>
            <div><dt>Repeats skipped</dt><dd>{pump?.skipped_identical.toLocaleString() ?? 0}</dd></div>
          </dl>
          <div className="budget">
            <div className="budget-bar"><span style={{ width: `${Math.max(0.5, budget * 100)}%` }} /></div>
            <p className="hint">
              {(link?.sequence ?? 0).toLocaleString()} of 16,777,216 message numbers used on this source address ({(budget * 100).toFixed(3)}%).
              Near the end the studio moves to a fresh source address on its own, so the budget never runs out.
            </p>
          </div>
        </Panel>

        <Panel title="Event log" aside={<ScrollText size={16} />} className="device-log">
          <ol className="log">
            {[...log].reverse().slice(0, 120).map((e, i) => (
              <li key={`${e.t}-${i}`} className={`log-${e.kind}`}>
                <time>{new Date(e.t * 1000).toLocaleTimeString()}</time>
                <span className="log-kind">{e.kind}</span>
                <span>{e.text}</span>
              </li>
            ))}
            {log.length === 0 && <li className="muted">Nothing yet.</li>}
          </ol>
        </Panel>
      </div>
      <AnimatePresence>{modelOpen && light && <ModelDialog light={light} onClose={() => setModelOpen(false)} />}</AnimatePresence>
    </div>
  )
}
