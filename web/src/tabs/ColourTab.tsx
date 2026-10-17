import { ImagePlus, Play, Plus, X } from 'lucide-react'
import { useState, type DragEvent } from 'react'
import { Key, Panel, Segmented } from '../components/Controls'
import { HueWheel } from '../components/HueWheel'
import { ColorInput } from '../components/ParamField'
import { Slider } from '../components/Slider'
import { hexToRgb, hsvToRgb, hueName, rgbCss, rgbToHex, rgbToHsv } from '../lib/color'
import { extractColumns, extractPalette } from '../lib/palette'
import { channelTrack, hueTrack, satTrack } from '../lib/tracks'
import { EMPTY, useStudio } from '../state/store'
import './tabs.css'

const HARMONIES: { id: string; name: string; offsets: number[] }[] = [
  { id: 'complement', name: 'Complement', offsets: [0, 180] },
  { id: 'triad', name: 'Triad', offsets: [0, 120, 240] },
  { id: 'split', name: 'Split', offsets: [0, 150, 210] },
  { id: 'analogous', name: 'Analogous', offsets: [-30, 0, 30] },
  { id: 'square', name: 'Square', offsets: [0, 90, 180, 270] },
]

const CHANNELS = [
  { key: 'r', name: 'Red', color: '#ff3b30' },
  { key: 'g', name: 'Green', color: '#34c759' },
  { key: 'b', name: 'Blue', color: '#0a84ff' },
  { key: 'w', name: 'White', color: '#f2efe8' },
] as const

export function ColourTab() {
  const state = useStudio((s) => s.state)
  const caps = useStudio((s) => s.caps)
  const apply = useStudio((s) => s.apply)
  const send = useStudio((s) => s.send)
  const swatches = useStudio((s) => s.store?.swatches ?? EMPTY)
  const upsert = useStudio((s) => s.upsert)
  const remove = useStudio((s) => s.remove)
  const toast = useStudio((s) => s.toast)
  const [harmony, setHarmony] = useState('complement')
  const [extracted, setExtracted] = useState<string[]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [dragging, setDragging] = useState(false)
  if (!state || !caps) return null

  const hasHsi = caps.features.colour
  const hasRgb = caps.features.channels
  const { hue, sat } = state.hsi
  const hex = rgbToHex(hsvToRgb(hue, sat))
  const setHs = (h: number, s: number) => apply({ power: true, mode: 'hsi', hsi: { hue: h, sat: s } })
  const setHex = (value: string) => {
    const [h, s] = rgbToHsv(hexToRgb(value))
    setHs(Math.round(h), Math.round(s))
  }
  const offsets = HARMONIES.find((x) => x.id === harmony)?.offsets ?? [0]
  const harmonyColors = offsets.map((o) => ({ hue: (hue + o + 360) % 360, sat }))

  const loadImage = async (file: File | undefined) => {
    if (!file || !file.type.startsWith('image/')) {
      toast('Drop an image file (JPG, PNG, WebP)', 'error')
      return
    }
    try {
      const [colors, strips] = await Promise.all([extractPalette(file), extractColumns(file)])
      if (!colors.length) toast('That image is too grey or dark to make a palette', 'error')
      setExtracted(colors)
      setColumns(strips)
    } catch (err) {
      toast((err as Error).message, 'error')
    }
  }
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    void loadImage(e.dataTransfer.files[0])
  }

  if (!hasHsi && !hasRgb) return <Panel><p className="muted">{caps.name} has no colour modes.</p></Panel>

  return (
    <div className="colour">
      <Panel className="colour-main">
        <div className="colour-wheel-wrap">
          <HueWheel hue={hue} sat={sat} onChange={setHs} size={320} marks={harmonyColors.slice(1)} />
        </div>
        <div className="colour-controls">
          <div className="colour-head">
            <span className="colour-big-swatch" style={{ background: hex }} />
            <div>
              <p className="readout colour-name">{hueName(hue)}</p>
              <p className="muted">{hue}° hue, {sat}% saturation{state.mode !== 'hsi' && ', not active yet'}</p>
            </div>
          </div>
          <Slider label="Hue" value={hue} min={0} max={359} step={1} track={hueTrack()} onChange={(h) => setHs(h, sat)} format={(v) => `${v}°`} />
          <Slider label="Saturation" value={sat} min={0} max={100} step={1} track={satTrack(hue)} onChange={(s) => setHs(hue, s)} format={(v) => `${v}%`} />
          <ColorInput value={hex} onChange={setHex} />
          {state.mode !== 'hsi' && <Key kind="primary" onClick={() => setHs(hue, sat)}>Use this colour</Key>}
        </div>
      </Panel>

      <div className="colour-grid">
        <Panel title="Harmony">
          <div className="harmony-pick">
            <Segmented size="sm" label="Harmony" value={harmony} onChange={setHarmony} options={HARMONIES.map((h) => ({ value: h.id, label: h.name }))} />
          </div>
          <div className="swatch-row">
            {harmonyColors.map((c, i) => (
              <button key={i} type="button" className="swatch-big" style={{ background: rgbCss(hsvToRgb(c.hue, c.sat)) }}
                onClick={() => setHs(c.hue, c.sat)} title={`${hueName(c.hue)}, ${c.hue}°`}>
                <span>{c.hue}°</span>
              </button>
            ))}
            <Key kind="ghost" title="Cycle through these colours"
              onClick={() => send({ type: 'engine.start', effect: 'palette', params: { colors: harmonyColors.map((c) => rgbToHex(hsvToRgb(c.hue, c.sat))), brightness: state.brightness } })}>
              <Play /> Cycle
            </Key>
          </div>
        </Panel>

        <Panel title="Your swatches" aside={
          <Key kind="ghost" onClick={() => upsert('swatches', { name: hueName(hue), hex })}><Plus /> Add current</Key>
        }>
          {swatches.length === 0 ? (
            <p className="muted">Colours you add here are kept between sessions.</p>
          ) : (
            <div className="swatch-row">
              {swatches.map((s) => (
                <div key={s.id} className="swatch-saved">
                  <button type="button" className="swatch-big" style={{ background: String(s.hex) }} onClick={() => setHex(String(s.hex))} title={String(s.hex)} />
                  <button type="button" className="swatch-remove" aria-label={`Remove ${s.name}`} onClick={() => remove('swatches', s.id)}><X size={12} /></button>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Palette from an image">
          <label className={`dropzone ${dragging ? 'is-over' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)} onDrop={onDrop}>
            <input type="file" accept="image/*" className="sr-only" onChange={(e) => void loadImage(e.target.files?.[0])} />
            <ImagePlus size={22} />
            <span>Drop a photo, film still or album cover, or click to choose one</span>
          </label>
          {extracted.length > 0 && (
            <div className="swatch-row" style={{ marginTop: 14 }}>
              {extracted.map((c) => (
                <button key={c} type="button" className="swatch-big" style={{ background: c }} onClick={() => setHex(c)} title={c} />
              ))}
              <Key kind="ghost" onClick={() => send({ type: 'engine.start', effect: 'palette', params: { colors: extracted, brightness: state.brightness } })}>
                <Play /> Play as palette
              </Key>
            </div>
          )}
          {columns.length > 0 && (
            <div className="scan-row">
              <div className="palette-strip" style={{ background: `linear-gradient(90deg, ${columns.join(', ')})` }} />
              <Key kind="ghost" title="Play the picture left to right, like a slow pan across it"
                onClick={() => send({ type: 'engine.start', effect: 'scan', params: { colors: columns, seconds: 30, brightness: Math.max(30, state.brightness) } })}>
                <Play /> Play as a scan
              </Key>
            </div>
          )}
        </Panel>

        {hasRgb && (
          <Panel title="Channel mixer" aside={<span>0 to 1000 per channel</span>}>
            <div className="faders">
              {CHANNELS.map((ch) => (
                <div key={ch.key} className="fader-col">
                  <Slider vertical label={`${ch.name} channel`} value={state.rgbw[ch.key]} min={0} max={1000} step={5}
                    track={channelTrack(ch.color)}
                    onChange={(v) => apply({ power: true, mode: 'rgbw', rgbw: { [ch.key]: v } })} />
                  <span className="fader-name">{ch.name}</span>
                </div>
              ))}
            </div>
            <p className="hint">Drives each LED directly. This frame is longer than a colour frame and goes out in several radio packets, so use the wheel for anything animated.</p>
          </Panel>
        )}
      </div>
    </div>
  )
}
