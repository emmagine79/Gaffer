import { Camera, Play, Plus, Save, Square, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react'
import { Field, Key, Panel, Segmented, Toggle } from '../components/Controls'
import { emission, hsvToRgb, kelvinToRgb, rgbCss } from '../lib/color'
import type { Keyframe, LightState, StatePatch, Timeline } from '../lib/types'
import { EMPTY, useStudio } from '../state/store'
import './tabs.css'

const EASES = [
  { value: 'inout', label: 'Smooth' }, { value: 'linear', label: 'Linear' },
  { value: 'in', label: 'Ease in' }, { value: 'out', label: 'Ease out' }, { value: 'step', label: 'Cut' },
]

const cct = (b: number, k: number): StatePatch => ({ power: true, mode: 'cct', brightness: b, cct: { kelvin: k, gm: 0 } })
const hsi = (b: number, h: number, s = 100): StatePatch => ({ power: true, mode: 'hsi', brightness: b, hsi: { hue: h, sat: s } })

const TEMPLATES: { name: string; loop: boolean; keyframes: Keyframe[] }[] = [
  { name: 'Warm to cool', loop: true, keyframes: [
    { t: 0, state: cct(55, 2200), ease: 'inout' }, { t: 6, state: cct(70, 6500), ease: 'inout' }, { t: 12, state: cct(55, 2200), ease: 'inout' },
  ] },
  { name: 'Colour tour', loop: true, keyframes: [0, 60, 120, 180, 240, 300, 360].map((h, i) => ({ t: i * 2, state: hsi(60, h % 360), ease: 'inout' })) },
  { name: 'Slow pulse', loop: true, keyframes: [
    { t: 0, state: hsi(8, 330), ease: 'inout' }, { t: 1.6, state: hsi(80, 330), ease: 'in' }, { t: 4, state: hsi(8, 330), ease: 'inout' },
  ] },
  { name: 'Dusk', loop: false, keyframes: [
    { t: 0, state: cct(80, 5600), ease: 'inout' }, { t: 8, state: cct(65, 3000), ease: 'inout' },
    { t: 14, state: hsi(35, 22, 95), ease: 'inout' }, { t: 20, state: hsi(6, 350, 90), ease: 'inout' },
  ] },
]

function patchColor(p: StatePatch, base: LightState): string {
  const s = { ...base, ...p, cct: { ...base.cct, ...(p.cct ?? {}) }, hsi: { ...base.hsi, ...(p.hsi ?? {}) }, rgbw: { ...base.rgbw, ...(p.rgbw ?? {}) } } as LightState
  if (s.mode === 'cct') return rgbCss(kelvinToRgb(s.cct.kelvin))
  if (s.mode === 'hsi') return rgbCss(hsvToRgb(s.hsi.hue, s.hsi.sat))
  return rgbCss(emission(s).rgb)
}

const snapshot = (s: LightState): StatePatch => {
  const { fx: _fx, ...rest } = s
  void _fx
  return { ...rest, power: true }
}

export function TimelineTab() {
  const state = useStudio((s) => s.state)
  const engine = useStudio((s) => s.engine)
  const send = useStudio((s) => s.send)
  const saved = useStudio((s) => (s.store?.timelines ?? EMPTY) as Timeline[])
  const upsert = useStudio((s) => s.upsert)
  const toast = useStudio((s) => s.toast)
  const [name, setName] = useState('Warm to cool')
  const [loop, setLoop] = useState(true)
  const [keys, setKeys] = useState<Keyframe[]>(TEMPLATES[0].keyframes)
  const [selected, setSelected] = useState(0)
  const [playhead, setPlayhead] = useState(0)
  const [savedId, setSavedId] = useState<string | undefined>()
  const laneRef = useRef<HTMLDivElement>(null)
  const playStart = useRef<number | null>(null)
  const saving = useRef(false)
  const loadGeneration = useRef(0)

  const duration = Math.max(1, ...keys.map((k) => k.t))
  const playing = engine.kind === 'timeline'

  // Re-anchored on every engine report, against the duration that is actually playing.
  const playingDuration = engine.duration ?? duration
  useEffect(() => {
    if (!playing) { playStart.current = null; return }
    playStart.current = performance.now() - engine.elapsed * 1000
  }, [playing, engine.elapsed])
  useEffect(() => {
    if (!playing) return
    let raf = 0
    const tick = () => {
      const t = (performance.now() - (playStart.current ?? performance.now())) / 1000
      setPlayhead(loop ? t % playingDuration : Math.min(t, playingDuration))
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, loop, playingDuration])

  const sorted = useMemo(() => [...keys].map((k, i) => ({ ...k, i })).sort((a, b) => a.t - b.t), [keys])
  if (!state) return null

  const gradient = `linear-gradient(90deg, ${sorted.map((k) => `${patchColor(k.state, state)} ${(k.t / duration) * 100}%`).join(', ')})`
  const curve = sorted.map((k) => `${(k.t / duration) * 1000},${100 - (Number(k.state.brightness ?? state.brightness))}`).join(' ')
  const sel = keys[selected]

  const update = (i: number, patch: Partial<Keyframe>) => setKeys((ks) => ks.map((k, j) => (j === i ? { ...k, ...patch } : k)))
  const timeAt = (clientX: number) => {
    const rect = laneRef.current?.getBoundingClientRect()
    if (!rect) return 0
    return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width)) * duration
  }
  const drag = (i: number) => (e: PointerEvent) => {
    e.stopPropagation()
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    setSelected(i)
  }
  const dragMove = (i: number) => (e: PointerEvent) => {
    if (!(e.currentTarget as HTMLElement).hasPointerCapture(e.pointerId)) return
    update(i, { t: Math.round(timeAt(e.clientX) * 10) / 10 })
  }

  const play = () => send({ type: 'timeline.play', timeline: { name, loop, keyframes: keys } })
  const addAtPlayhead = () => {
    const t = Math.round(playhead * 10) / 10
    setKeys((ks) => [...ks, { t, state: snapshot(state), ease: 'inout' }])
    setSelected(keys.length)
  }
  const save = async () => {
    if (saving.current) return
    saving.current = true
    const generation = loadGeneration.current
    try {
      const item = await upsert('timelines', { id: savedId, name, loop, keyframes: keys, duration })
      if (item && generation === loadGeneration.current) { setSavedId(item.id); toast(`Saved "${name}"`, 'ok') }
    } finally {
      saving.current = false
    }
  }
  const load = (t: { name: string; loop: boolean; keyframes: Keyframe[]; id?: string }) => {
    loadGeneration.current += 1
    setName(t.name); setLoop(t.loop); setKeys(t.keyframes); setSelected(0); setSavedId(t.id); setPlayhead(0)
  }

  return (
    <div className="timeline">
      <Panel className="tl-bar">
        <div className="tl-toolbar">
          <input className="input tl-name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Timeline name" />
          {playing
            ? <Key kind="live" onClick={() => send({ type: 'engine.stop', restore: false })}><Square /> Stop</Key>
            : <Key kind="primary" onClick={play} disabled={keys.length < 2}><Play /> Play</Key>}
          <label className="tl-loop"><Toggle on={loop} onChange={setLoop} label="Loop" /> Loop</label>
          <span className="muted">{duration.toFixed(1)} s, {keys.length} keyframes</span>
          <span className="tl-spacer" />
          <Key kind="ghost" onClick={save}><Save /> Save</Key>
          <select className="input tl-load" value="" onChange={(e) => {
            const t = TEMPLATES.find((x) => x.name === e.target.value) ?? saved.find((x) => x.id === e.target.value)
            if (t) load(t as Timeline)
          }} aria-label="Open a timeline">
            <option value="">Open</option>
            <optgroup label="Starters">{TEMPLATES.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}</optgroup>
            {saved.length > 0 && <optgroup label="Saved">{saved.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</optgroup>}
          </select>
        </div>

        <div className="tl-ruler" onPointerDown={(e) => !playing && setPlayhead(timeAt(e.clientX))}>
          {Array.from({ length: Math.floor(duration) + 1 }, (_, s) => (
            <span key={s} style={{ left: `${(s / duration) * 100}%` }}>{s % Math.max(1, Math.round(duration / 10)) === 0 ? `${s}s` : ''}</span>
          ))}
        </div>
        <div className="tl-lanes" ref={laneRef} onPointerDown={(e) => !playing && setPlayhead(timeAt(e.clientX))}>
          <div className="tl-colour" style={{ background: gradient }} />
          <svg className="tl-curve" viewBox="0 0 1000 100" preserveAspectRatio="none" aria-hidden="true">
            <polyline points={curve} fill="none" stroke="rgb(255 255 255 / 0.8)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
          </svg>
          {keys.map((k, i) => (
            <button
              key={i}
              type="button"
              className={`tl-key ${i === selected ? 'is-on' : ''}`}
              style={{ left: `${(k.t / duration) * 100}%`, background: patchColor(k.state, state) }}
              onPointerDown={drag(i)}
              onPointerMove={dragMove(i)}
              aria-label={`Keyframe at ${k.t} seconds`}
            />
          ))}
          <span className="tl-playhead" style={{ left: `${(playhead / duration) * 100}%` }} />
        </div>
        <div className="tl-under">
          <Key onClick={addAtPlayhead}><Plus /> Add the current look at {playhead.toFixed(1)} s</Key>
          <span className="hint">Drag keyframes to retime them. Click the lane to move the playhead.</span>
        </div>
      </Panel>

      {sel && (
        <Panel title={`Keyframe at ${sel.t.toFixed(1)} s`} aside={
          <Key kind="danger" disabled={keys.length <= 2} onClick={() => { setKeys((ks) => ks.filter((_, j) => j !== selected)); setSelected(0) }}><Trash2 /> Delete</Key>
        }>
          <div className="tl-editor">
            <span className="tl-editor-swatch" style={{ background: patchColor(sel.state, state) }} />
            <Field label="Time (seconds)">
              <input className="input" type="number" min={0} step={0.1} value={sel.t} onChange={(e) => update(selected, { t: Math.max(0, Number(e.target.value)) })} />
            </Field>
            <Field label="Arrive with">
              <Segmented size="sm" label="Easing" value={sel.ease} onChange={(ease) => update(selected, { ease })} options={EASES} />
            </Field>
            <Key onClick={() => update(selected, { state: snapshot(state) })}><Camera /> Use the current look</Key>
            <Key kind="ghost" onClick={() => send({ type: 'set', patch: sel.state, fade: 0.3 })}>Preview this keyframe</Key>
          </div>
        </Panel>
      )}
    </div>
  )
}
