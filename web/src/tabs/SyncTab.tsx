import { Mic, MonitorUp, Music, Square } from 'lucide-react'
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { Field, Key, Panel, Segmented, Toggle } from '../components/Controls'
import { ParamField } from '../components/ParamField'
import { Slider } from '../components/Slider'
import type { Zone } from '../lib/ambient'
import { hsvToRgb, hueName, kelvinToRgb, rgbCss } from '../lib/color'
import { onWorkerMessage } from '../lib/streamClient'
import { analyser, useSync, type MusicConfig } from '../state/syncSessions'
import './tabs.css'

const MODES: { value: MusicConfig['mode']; label: string; hint: string }[] = [
  { value: 'pulse', label: 'Pulse', hint: 'Brightness rides the loudness; colour drifts with the treble' },
  { value: 'beat', label: 'Beat colour', hint: 'Jumps to the next palette colour on every kick' },
  { value: 'spectrum', label: 'Spectrum', hint: 'Bass-heavy moments go red, vocals amber, cymbals blue' },
  { value: 'strobe', label: 'Beat strobe', hint: 'A white flash on every kick, dark between' },
]

const pct = (v: number) => `${Math.round(v * 100)}%`

export function SyncTab() {
  return (
    <div className="sync">
      <MusicSync />
      <ScreenSync />
      <p className="hint sync-note">
        Both keep running while you use other tabs, and while this window is hidden behind your music player or the
        window you are sharing: the audio is analysed on the browser's audio thread and the screen in a background worker.
      </p>
    </div>
  )
}

function MusicSync() {
  const phase = useSync((s) => s.music)
  const cfg = useSync((s) => s.musicConfig)
  const setCfg = useSync((s) => s.setMusicConfig)
  const start = useSync((s) => s.startMusic)
  const stop = useSync((s) => s.stopMusic)
  const canvas = useRef<HTMLCanvasElement>(null)
  const meterBar = useRef<HTMLSpanElement>(null)
  const beatTag = useRef<HTMLElement>(null)
  const colour = useRef('#f4f1ea')

  // Meter updates arrive ~20 times a second from the worker; write the DOM directly instead of re-rendering.
  useEffect(() => onWorkerMessage((m) => {
    if (m.type !== 'meter') return
    if (meterBar.current) meterBar.current.style.width = `${Number(m.level) * 100}%`
    beatTag.current?.classList.toggle('is-beat', Boolean(m.beat))
    const f = m.frame as { mode: string; hue?: number; sat?: number }
    colour.current = f.mode === 'hsi' ? rgbCss(hsvToRgb(Number(f.hue), Number(f.sat))) : '#f4f1ea'
  }), [])

  // The spectrum is decoration: drawn only while visible.
  useEffect(() => {
    if (phase !== 'running') return
    let raf = 0
    const bins = new Uint8Array(1024)
    const draw = () => {
      const c = canvas.current
      const g = c?.getContext('2d')
      const a = analyser()
      if (c && g && a) {
        a.getByteFrequencyData(bins)
        g.clearRect(0, 0, c.width, c.height)
        g.fillStyle = colour.current
        const bars = 72
        for (let i = 0; i < bars; i++) {
          const v = bins[Math.floor(Math.pow(i / bars, 2) * 400)] / 255
          const h = Math.max(2, v * c.height)
          g.globalAlpha = 0.35 + v * 0.65
          g.fillRect((i * c.width) / bars + 1, c.height - h, c.width / bars - 3, h)
        }
        g.globalAlpha = 1
      }
      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [phase])

  const current = MODES.find((m) => m.value === cfg.mode)
  return (
    <Panel title="Follow music" aside={phase === 'running' ? <span className="live-pill">Listening</span> : <Music size={16} />}>
      <canvas ref={canvas} className="spectrum" width={720} height={140} aria-label="Live spectrum" />
      <div className="meter"><span ref={meterBar} /><i ref={beatTag}>Beat</i></div>
      <div className="sync-actions">
        {phase === 'running' ? (
          <Key kind="live" onClick={stop}><Square /> Stop listening</Key>
        ) : (
          <>
            <Key kind="primary" disabled={phase === 'starting'} onClick={() => void start('tab')}><MonitorUp /> Listen to a tab or the system</Key>
            <Key disabled={phase === 'starting'} onClick={() => void start('mic')}><Mic /> Use the microphone</Key>
            {phase === 'starting' && <Key kind="ghost" onClick={stop}>Cancel</Key>}
          </>
        )}
      </div>
      <Field label="Mode" hint={current?.hint}>
        <Segmented label="Mode" value={cfg.mode} onChange={(mode) => setCfg({ mode })} options={MODES} />
      </Field>
      <div className="sync-grid">
        <Field label="Sensitivity"><Slider label="Sensitivity" value={cfg.sensitivity} min={0} max={1} step={0.01} onChange={(sensitivity) => setCfg({ sensitivity })} format={pct} /></Field>
        <Field label="Smoothing"><Slider label="Smoothing" value={cfg.smoothing} min={0} max={1} step={0.01} onChange={(smoothing) => setCfg({ smoothing })} format={pct} /></Field>
        <Field label="Quietest"><Slider label="Floor" value={cfg.floor} min={0} max={50} step={1} onChange={(floor) => setCfg({ floor })} format={(v) => `${v}%`} /></Field>
        <Field label="Loudest"><Slider label="Ceiling" value={cfg.ceiling} min={10} max={100} step={1} onChange={(ceiling) => setCfg({ ceiling })} format={(v) => `${v}%`} /></Field>
      </div>
      <ParamField spec={{ key: 'palette', label: cfg.mode === 'pulse' ? 'Base colour (first) and palette' : 'Palette', kind: 'palette', default: cfg.palette }}
        value={cfg.palette} onChange={(v) => setCfg({ palette: v as string[] })} />
    </Panel>
  )
}

const ZONES: { value: Zone; label: string }[] = [
  { value: 'whole', label: 'Whole screen' }, { value: 'edges', label: 'Edges' }, { value: 'centre', label: 'Centre' },
  { value: 'left', label: 'Left' }, { value: 'right', label: 'Right' }, { value: 'top', label: 'Top' }, { value: 'bottom', label: 'Bottom' },
]

const ZONE_BOX: Record<Zone, CSSProperties> = {
  whole: { inset: 0 },
  edges: { inset: 0 },
  centre: { left: '25%', right: '25%', top: '25%', bottom: '25%' },
  left: { left: 0, width: '25%', top: 0, bottom: 0 },
  right: { right: 0, width: '25%', top: 0, bottom: 0 },
  top: { left: 0, right: 0, top: 0, height: '30%' },
  bottom: { left: 0, right: 0, bottom: 0, height: '30%' },
}

interface ScreenReport {
  analysis: { mode: 'cct' | 'hsi'; palette: { hex: string; share: number }[]; chromaShare: number }
  out: { mode: 'cct' | 'hsi'; hue: number; sat: number; kelvin: number; brightness: number }
}

function ScreenSync() {
  const phase = useSync((s) => s.screen)
  const cfg = useSync((s) => s.screenConfig)
  const setCfg = useSync((s) => s.setScreenConfig)
  const start = useSync((s) => s.startScreen)
  const stop = useSync((s) => s.stopScreen)
  const thumb = useRef<HTMLCanvasElement>(null)
  const [report, setReport] = useState<ScreenReport | null>(null)

  useEffect(() => onWorkerMessage((m) => {
    if (m.type === 'screen') setReport({ analysis: m.analysis as ScreenReport['analysis'], out: m.out as ScreenReport['out'] })
    if (m.type === 'screen-thumb') {
      const bitmap = m.bitmap as ImageBitmap
      const g = thumb.current?.getContext('2d')
      if (g) g.drawImage(bitmap, 0, 0, g.canvas.width, g.canvas.height)
      bitmap.close()
    }
  }), [])

  const running = phase === 'running'
  const out = report?.out
  const swatch = out ? (out.mode === 'cct' ? rgbCss(kelvinToRgb(out.kelvin)) : rgbCss(hsvToRgb(out.hue, out.sat))) : '#2b2c30'
  const outLabel = !out ? 'Waiting for the first frame'
    : out.mode === 'cct' ? `White, ${Math.round(out.kelvin / 50) * 50} K at ${Math.round(out.brightness)}%`
    : `${hueName(out.hue)}, ${Math.round(out.sat)}% saturation at ${Math.round(out.brightness)}%`
  const why = !report ? '' : report.analysis.mode === 'cct'
    ? 'Mostly neutral, so it uses the light\u2019s true white'
    : `The most covered colour takes ${Math.round(report.analysis.chromaShare * 100)}% of what it can see`

  return (
    <Panel title="Follow the screen" aside={running ? <span className="live-pill">Sampling</span> : <MonitorUp size={16} />}>
      <div className="screen-view">
        <div className="screen-thumb">
          <canvas ref={thumb} width={320} height={180} aria-label="What the studio sees" />
          {!running && <span className="screen-thumb-empty">Pick a screen, window or tab. Its picture shows here, with the area being followed outlined.</span>}
          <span className={`screen-zone screen-zone--${cfg.zone}`} style={ZONE_BOX[cfg.zone]} aria-hidden="true" />
        </div>
        <div className="screen-out">
          <span className="screen-out-swatch" style={{ background: swatch }} />
          <div>
            <strong>{running ? outLabel : 'Not following yet'}</strong>
            <p className="muted">{running ? why : 'Choose a screen to start.'}</p>
          </div>
        </div>
        {running && report && (
          <div className="screen-palette" aria-label="Colours found on screen">
            {report.analysis.palette.map((c, i) => (
              <span key={i} className="screen-palette-chip" style={{ background: c.hex, flexGrow: Math.max(0.04, c.share) }} title={`${c.hex}, ${Math.round(c.share * 100)}%`} />
            ))}
          </div>
        )}
      </div>

      <div className="sync-actions">
        {running
          ? <Key kind="live" onClick={stop}><Square /> Stop</Key>
          : <Key kind="primary" disabled={phase === 'starting'} onClick={() => void start()}><MonitorUp /> Choose what to follow</Key>}
      </div>

      <Field label="Style" hint={cfg.style === 'match' ? 'What the room would really look like lit by the screen' : 'Chases the most vivid colour, even a small one: for parties and music videos'}>
        <Segmented label="Style" value={cfg.style} onChange={(style) => setCfg({ style })} options={[{ value: 'match', label: 'Match the scene' }, { value: 'mood', label: 'Vivid mood' }]} />
      </Field>
      <Field label="Follow">
        <Segmented size="sm" label="Zone" value={cfg.zone} onChange={(zone) => setCfg({ zone })} options={ZONES} />
      </Field>
      <div className="sync-grid">
        <Field label="Smoothing"><Slider label="Smoothing" value={cfg.smooth} min={0} max={1} step={0.01} onChange={(smooth) => setCfg({ smooth })} format={pct} /></Field>
        <Field label="Warmth of whites"><Slider label="Warmth of whites" value={cfg.warmth} min={-2500} max={2500} step={100} onChange={(warmth) => setCfg({ warmth })} format={(v) => (v === 0 ? 'Screen' : `${v > 0 ? '+' : ''}${v} K`)} /></Field>
        <Field label="Dark scenes"><Slider label="Minimum brightness" value={cfg.low} min={0} max={50} step={1} onChange={(low) => setCfg({ low })} format={(v) => `${v}%`} /></Field>
        <Field label="Bright scenes"><Slider label="Maximum brightness" value={cfg.high} min={10} max={100} step={1} onChange={(high) => setCfg({ high })} format={(v) => `${v}%`} /></Field>
      </div>
      <div className="field field--row">
        <span className="field-label">Use true white for neutral scenes<span className="dim">off: always a colour</span></span>
        <Toggle label="Use true white for neutral scenes" on={cfg.whites} onChange={(whites) => setCfg({ whites })} />
      </div>
      <div className="field field--row">
        <span className="field-label">Add punch from the sound<span className="dim">share the tab with audio; applies on the next start</span></span>
        <Toggle label="Add punch from the sound" on={cfg.withAudio} onChange={(withAudio) => setCfg({ withAudio })} />
      </div>
      {cfg.withAudio && (
        <Field label="Punch"><Slider label="Punch" value={cfg.punch} min={0} max={1} step={0.01} onChange={(punch) => setCfg({ punch })} format={pct} /></Field>
      )}
    </Panel>
  )
}
