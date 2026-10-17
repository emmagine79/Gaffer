import { BookmarkPlus, Info, Play, Square, Zap } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { Field, Key, Panel, Segmented } from '../components/Controls'
import { Slider } from '../components/Slider'
import { InlineSave } from '../components/InlineSave'
import { ParamField } from '../components/ParamField'
import { effectFit, usableEffects } from '../effects/fit'
import type { BuiltinEffect, Caps, ParamSpec, SoftEffect } from '../lib/types'
import { EMPTY, useStudio } from '../state/store'
import './tabs.css'

type Source = 'engine' | 'builtin'

const defaultsOf = (params: ParamSpec[]) => Object.fromEntries(params.map((p) => [p.key, p.default]))

function AdaptNote({ caps }: { caps: Caps }) {
  let text: ReactNode = null
  if (caps.features.daylight) {
    text = <>The <b>{caps.name}</b> has one colour temperature, so effects play through its brightness. Those that only change colour are left out.</>
  } else if (!caps.features.colour) {
    text = <>The <b>{caps.name}</b> is bi-colour: colour effects play as warmth, red glowing warm and blue cool{caps.features.tint ? ', with green and magenta on its tint control' : ''}. Effects tagged <i>as warmth</i> are the ones that change.</>
  } else if (!caps.features.white) {
    text = <>The <b>{caps.name}</b> has no white mode, so white effects play as the hue of each temperature.</>
  }
  if (!text) return null
  return <div className="adapt-note"><Info size={16} /><p>{text}</p></div>
}

export function EffectsTab() {
  const [chosen, setSource] = useState<Source>('engine')
  const effects = useStudio((s) => s.effects)
  const caps = useStudio((s) => s.caps)
  const builtin = caps?.effects.length ?? 0
  const source: Source = builtin ? chosen : 'engine'
  return (
    <div className="effects">
      <div className="effects-switch">
        {builtin > 0 && (
          <Segmented label="Effect source" value={source} onChange={setSource} options={[
            { value: 'engine', label: `Rendered live (${usableEffects(effects, caps).length})`, title: 'Computed by Gaffer and streamed to the light up to 80 times a second' },
            { value: 'builtin', label: `Built into the light (${builtin})`, title: 'Run by the light itself; nothing is streamed' },
          ]} />
        )}
      </div>
      {caps && source === 'engine' && <AdaptNote caps={caps} />}
      {source === 'engine' ? <EngineEffects /> : <BuiltinEffects />}
    </div>
  )
}

function EngineEffects() {
  const allEffects = useStudio((s) => s.effects)
  const engine = useStudio((s) => s.engine)
  const send = useStudio((s) => s.send)
  const caps = useStudio((s) => s.caps)
  const presets = useStudio((s) => s.store?.presets ?? EMPTY)
  const upsert = useStudio((s) => s.upsert)
  const toast = useStudio((s) => s.toast)
  const [category, setCategory] = useState('All')
  const [selectedId, setSelectedId] = useState<string>(() => engine.effect ?? 'aurora')
  const [drafts, setDrafts] = useState<Record<string, Record<string, unknown>>>({})

  const effects = useMemo(() => usableEffects(allEffects, caps), [allEffects, caps])
  const categories = useMemo(() => ['All', ...new Set(effects.map((e) => e.category))], [effects])
  const selected = effects.find((e) => e.id === selectedId) ?? effects[0]
  if (!selected || !caps) return null
  const kelvinRange: [number, number] = caps.features.white ? [caps.min_kelvin, caps.max_kelvin] : [1800, 10000]

  const running = engine.kind === 'effect' && engine.effect === selected.id
  const values: Record<string, unknown> = running
    ? { ...defaultsOf(selected.params), ...engine.params }
    : { ...defaultsOf(selected.params), ...(drafts[selected.id] ?? {}) }

  const setParam = (key: string, value: unknown) => {
    setDrafts((d) => ({ ...d, [selected.id]: { ...(d[selected.id] ?? {}), [key]: value } }))
    if (running) send({ type: 'engine.params', params: { [key]: value } })
  }
  const start = (fx: SoftEffect, params?: Record<string, unknown>) =>
    send({ type: 'engine.start', effect: fx.id, params: params ?? { ...defaultsOf(fx.params), ...(drafts[fx.id] ?? {}) } })

  return (
    <div className="fx-layout">
      <div className="fx-list">
        <Segmented size="sm" label="Category" value={category} onChange={setCategory} options={categories.map((c) => ({ value: c, label: c }))} />
        <div className="fx-grid">
          {effects.filter((e) => category === 'All' || e.category === category).map((fx) => {
            const isRunning = engine.kind === 'effect' && engine.effect === fx.id
            return (
              <button
                key={fx.id}
                type="button"
                className={`fx-tile ${fx.id === selected.id ? 'is-selected' : ''} ${isRunning ? 'is-running' : ''}`}
                style={{ ['--accent' as string]: fx.accent }}
                onClick={() => setSelectedId(fx.id)}
                onDoubleClick={() => start(fx)}
              >
                <span className="fx-tile-glow" />
                <span className="fx-tile-name">{fx.name}</span>
                <span className="fx-tile-cat">{fx.category}{effectFit(fx, caps) && <span className="fx-tag">{effectFit(fx, caps)}</span>}</span>
                {isRunning && <span className="tally fx-tile-tally" />}
              </button>
            )
          })}
        </div>
        <p className="hint">Double-click a tile to start it straight away.</p>
      </div>

      <Panel className="fx-detail" title={selected.name} aside={running ? <span className="live-pill">Live</span> : null}>
        <p className="muted fx-desc">{selected.description}</p>
        <div className="fx-actions">
          {running ? (
            <Key kind="live" onClick={() => send({ type: 'engine.stop' })}><Square /> Stop</Key>
          ) : (
            <Key kind="primary" onClick={() => start(selected)}><Play /> Start</Key>
          )}
          {selected.trigger && (
            <Key onClick={() => running ? send({ type: 'engine.trigger' }) : toast('Start the effect first, then trigger it', 'info')} className="fx-trigger">
              <Zap /> {selected.trigger}
            </Key>
          )}
          <InlineSave label="Save preset" icon={<BookmarkPlus />} placeholder="Preset name"
            onSave={async (name) => {
              const item = await upsert('presets', { name, effect: selected.id, params: values })
              if (item) toast(`Saved preset "${name}"`, 'ok')
            }} />
        </div>
        <div className="fx-params">
          {selected.params.map((p) => (
            <ParamField key={p.key} spec={p} value={values[p.key]} siblings={values} onChange={(v) => setParam(p.key, v)}
              kelvinRange={kelvinRange} />
          ))}
        </div>
        {presets.length > 0 && (
          <div className="fx-presets">
            <h4>Presets</h4>
            {presets.map((p) => {
              const fx = effects.find((e) => e.id === p.effect)
              return (
                <button key={p.id} type="button" className="preset-row" onClick={() => { if (fx) { setSelectedId(fx.id); setDrafts((d) => ({ ...d, [fx.id]: p.params })); start(fx, p.params) } }}>
                  <span className="preset-dot" style={{ background: fx?.accent }} />
                  <span>{p.name}</span>
                  <span className="muted">{fx?.name}</span>
                </button>
              )
            })}
          </div>
        )}
      </Panel>
    </div>
  )
}

function BuiltinEffects() {
  const caps = useStudio((s) => s.caps)
  const state = useStudio((s) => s.state)
  const apply = useStudio((s) => s.apply)
  const [selected, setSelected] = useState<number>(() => state?.fx?.symbol ?? caps?.effects[0]?.symbol ?? 0)
  const [drafts, setDrafts] = useState<Record<number, Record<string, number>>>({})
  const [speeds, setSpeeds] = useState<Record<number, number>>({})
  if (!caps || !state) return null
  const fx: BuiltinEffect | undefined = caps.effects.find((e) => e.symbol === selected)
  if (!fx) return <Panel><p className="muted">{caps.name} has no built-in effects.</p></Panel>

  const active = state.mode === 'fx' && state.fx?.symbol === fx.symbol
  const values: Record<string, number> = {
    ...(defaultsOf(fx.params) as Record<string, number>),
    ...(active ? state.fx?.params ?? {} : drafts[fx.symbol] ?? {}),
  }
  // The older effect generation has no parameters, only a speed counted in gears.
  const gears = fx.params.length === 0 && fx.speed_max > 0
  const speed = active ? state.fx?.speed ?? 0 : speeds[fx.symbol] ?? 0
  const run = (params: Record<string, number>, withSpeed = speed) =>
    apply({ power: true, mode: 'fx', fx: { symbol: fx.symbol, speed: gears ? withSpeed : null, params } })
  const setParam = (key: string, value: unknown) => {
    const next = { ...values, [key]: Number(value) }
    setDrafts((d) => ({ ...d, [fx.symbol]: next }))
    if (active) run(next)
  }
  const setSpeed = (v: number) => {
    setSpeeds((d) => ({ ...d, [fx.symbol]: v }))
    if (active) run(values, v)
  }

  return (
    <div className="fx-layout">
      <div className="fx-list">
        <div className="fx-grid">
          {caps.effects.map((e) => {
            const on = state.mode === 'fx' && state.fx?.symbol === e.symbol
            return (
              <button key={e.symbol} type="button" className={`fx-tile fx-tile--builtin ${e.symbol === selected ? 'is-selected' : ''} ${on ? 'is-running' : ''}`}
                onClick={() => setSelected(e.symbol)} onDoubleClick={() => { setSelected(e.symbol); apply({ power: true, mode: 'fx', fx: { symbol: e.symbol, speed: null, params: drafts[e.symbol] ?? {} } }) }}>
                <span className="fx-tile-glow" />
                <span className="fx-tile-name">{e.name}</span>
                <span className="fx-tile-cat">{e.params.length ? `${e.params.length} settings` : e.speed_max ? `${e.speed_max + 1} speeds` : 'one speed'}</span>
                {on && <span className="tally fx-tile-tally" />}
              </button>
            )
          })}
        </div>
        <p className="hint">These run inside the light, so they cost no Bluetooth traffic and keep going if this computer sleeps. Ranges marked inferred come from the vendor app's defaults; the light clamps anything it does not accept.</p>
      </div>
      <Panel className="fx-detail" title={fx.name} aside={active ? <span className="live-pill">On the light</span> : null}>
        <div className="fx-actions">
          {active ? (
            <Key onClick={() => apply({ mode: 'cct' }, { fade: 0.4 })}><Square /> Back to white</Key>
          ) : (
            <Key kind="primary" onClick={() => run(values)}><Play /> Run on the light</Key>
          )}
        </div>
        <div className="fx-params">
          {gears && (
            <Field label="Speed">
              <Slider label="Speed" value={speed} min={0} max={fx.speed_max} step={1} onChange={setSpeed}
                format={(v) => `${v + 1} of ${fx.speed_max + 1}`} />
            </Field>
          )}
          {fx.params.map((p) => (
            <ParamField key={p.key} spec={p} value={values[p.key]} siblings={values} onChange={(v) => setParam(p.key, v)}
              kelvinRange={caps.features.white ? [caps.min_kelvin, caps.max_kelvin] : [1800, 10000]} />
          ))}
        </div>
      </Panel>
    </div>
  )
}
