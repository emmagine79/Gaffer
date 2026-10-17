/// <reference lib="webworker" />
/**
 * The real-time path for music and screen sync, off the main thread.
 *
 * A hidden tab gets no animation frames and timers throttled to about once a
 * second, which would drop music sync to 1 fps the moment the music player is
 * in front. This worker sidesteps all of it:
 *
 *   audio:  AudioWorklet (audio thread) --MessagePort--> here
 *   screen: MediaStreamTrackProcessor frames --transferred stream--> here
 *   out:    its own WebSocket ("role=stream") --> studio server --> pump --> light
 *
 * The page only sends configuration and receives meters and previews for display.
 */
import { AmbientTracker, analyse, type Style, type Zone } from '../lib/ambient'
import { clamp, hexToRgb, rgbToHsv } from '../lib/color'

interface AudioConfig { mode: 'pulse' | 'beat' | 'spectrum' | 'strobe'; sensitivity: number; smoothing: number; floor: number; ceiling: number; palette: string[] }
interface ScreenConfig { style: Style; zone: Zone; whites: boolean; warmth: number; low: number; high: number; smooth: number; punch: number }

const ctx = self as unknown as DedicatedWorkerGlobalScope
let url = ''
let ws: WebSocket | null = null
let rate = 40
let audioCfg: AudioConfig = { mode: 'pulse', sensitivity: 0.6, smoothing: 0.5, floor: 4, ceiling: 100, palette: ['#ff006e'] }
let screenCfg: ScreenConfig = { style: 'match', zone: 'whole', whites: true, warmth: 0, low: 6, high: 85, smooth: 0.45, punch: 0.5 }
let lastSent = 0
let audioPort: MessagePort | null = null
/** In combo mode the audio does not drive the light itself: it adds punch to the screen's colour. */
let audioCombo = false
let screenRunning = false
let lastScreenFrame: Record<string, unknown> | null = null
/** Sources with an open session. Frames for any other source are never sent. */
const open = new Set<string>()
/** begin/end must survive a reconnect: they queue until the socket is open. */
let control: Record<string, unknown>[] = []
/** The light this session drives: fixed when it starts, so selecting another light does not move it. */
let target: string | null = null

function connect() {
  ws = new WebSocket(url + (url.includes('?') ? '&' : '?') + 'role=stream')
  ws.onopen = () => {
    // After a reconnect the server forgot our sessions: reopen the live ones.
    const pending = control
    control = []
    // Ends first: a source stopped and restarted while offline must not have its
    // new session closed by the old one's end.
    for (const m of pending) if (m.type === 'stream.end') ws?.send(JSON.stringify(m))
    for (const source of open) ws?.send(JSON.stringify({ type: 'stream.begin', source, light: target }))
  }
  ws.onclose = () => { ws = null; setTimeout(connect, 600) }
}

function sendControl(m: Record<string, unknown>) {
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(m))
  else control.push(m)
}

function begin(source: string) {
  open.add(source)
  sendControl({ type: 'stream.begin', source, light: target })
}

function end(source: string) {
  if (!open.delete(source)) return
  // Sent on this same socket, so it is ordered after every frame already sent.
  sendControl({ type: 'stream.end', source, light: target })
}

function send(frame: Record<string, unknown>, source: string, force = false) {
  if (!open.has(source)) return
  const now = performance.now()
  if (!force && now - lastSent < 1000 / rate) return
  if (ws?.readyState !== WebSocket.OPEN) return
  lastSent = now
  ws.send(JSON.stringify({ type: 'stream', frame, source, light: target }))
}

// ---------------------------------------------------------------- audio

const audio = { peak: 0.01, bassPeak: 0.01, level: 0, history: [] as number[], lastBeat: 0, beatIndex: 0, flash: 0, drift: 0, lastMeter: 0 }

function onBands(b: { bass: number; mid: number; treble: number; rms: number }) {
  const c = audioCfg
  const raw = b.bass * 0.5 + b.mid * 0.35 + b.treble * 0.15
  audio.peak = Math.max(raw, audio.peak * 0.997, 0.002)
  audio.bassPeak = Math.max(b.bass, audio.bassPeak * 0.997, 0.002)
  const target = clamp((raw / audio.peak) * (0.6 + c.sensitivity * 0.8), 0, 1)
  const k = target > audio.level ? 0.65 : 1 - c.smoothing * 0.9
  audio.level += (target - audio.level) * k

  const now = performance.now()
  audio.history.push(b.bass)
  if (audio.history.length > 43) audio.history.shift()
  const avg = audio.history.reduce((s, x) => s + x, 0) / audio.history.length
  const beat = b.bass > avg * (1.5 - c.sensitivity * 0.45) && b.bass > audio.bassPeak * 0.3 && now - audio.lastBeat > 180
  if (beat) { audio.lastBeat = now; audio.beatIndex++; audio.flash = 1 }
  audio.flash *= 0.84

  if (audioCombo) {
    // The screen decides the colour; a kick lands on the light at once rather
    // than waiting for the next video frame.
    if (beat && lastScreenFrame) send(punched(lastScreenFrame), 'screen', true)
    if (now - audio.lastMeter > 50) {
      audio.lastMeter = now
      ctx.postMessage({ type: 'meter', level: audio.level, beat: audio.flash > 0.6, frame: lastScreenFrame ?? { mode: 'cct' } })
    }
    return
  }

  const total = b.bass + b.mid + b.treble + 1e-6
  const centroid = clamp(((b.mid * 0.5 + b.treble) / total) * 1.5, 0, 1)
  const range = (x: number) => c.floor + (c.ceiling - c.floor) * x
  const pick = (i: number) => rgbToHsv(hexToRgb(c.palette[((i % c.palette.length) + c.palette.length) % c.palette.length] ?? '#ffffff'))

  let frame: Record<string, unknown>
  if (c.mode === 'pulse') {
    audio.drift = (audio.drift + 0.12 + (b.treble / (audio.peak + 1e-6)) * 0.3) % 360
    const [h, s] = pick(0)
    frame = { mode: 'hsi', hue: (h + audio.drift) % 360, sat: s, brightness: range(audio.level) }
  } else if (c.mode === 'beat') {
    const [h, s] = pick(audio.beatIndex)
    frame = { mode: 'hsi', hue: h, sat: s, brightness: range(Math.max(audio.level * 0.6, audio.flash)) }
  } else if (c.mode === 'spectrum') {
    frame = { mode: 'hsi', hue: (centroid * 240) % 360, sat: 92, brightness: range(audio.level) }
  } else {
    frame = { mode: 'cct', kelvin: 6500, brightness: audio.flash > 0.5 ? c.ceiling : c.floor }
  }
  send(frame, 'audio', beat)

  if (now - audio.lastMeter > 50) {
    audio.lastMeter = now
    ctx.postMessage({ type: 'meter', level: audio.level, beat: audio.flash > 0.6, frame })
  }
}

/** The screen's frame with the music's energy on top. */
function punched(frame: Record<string, unknown>): Record<string, unknown> {
  if (!audioCombo || audioPort === null) return frame
  const p = screenCfg.punch
  const base = Number(frame.brightness)
  const lifted = base * (1 - p) + p * base * (0.45 + 0.9 * audio.level) + p * 40 * audio.flash
  return { ...frame, brightness: clamp(lifted, 0, 100) }
}

// ---------------------------------------------------------------- screen

const W = 64
const H = 36

async function readScreen(readable: ReadableStream<VideoFrame>) {
  const reader = readable.getReader()
  const canvas = new OffscreenCanvas(W, H)
  const g = canvas.getContext('2d', { willReadFrequently: true })
  if (!g) return
  const tracker = new AmbientTracker()
  let lastSample = 0, lastPreview = 0, lastThumb = 0
  screenRunning = true
  begin('screen')
  while (screenRunning) {
    const { value: frame, done } = await reader.read()
    if (done || !frame) break
    if (!screenRunning) { frame.close(); break }
    const now = performance.now()
    if (now - lastSample >= 1000 / Math.max(rate, 10)) {
      lastSample = now
      g.drawImage(frame, 0, 0, W, H)
      const data = g.getImageData(0, 0, W, H).data
      const a = analyse(data, W, H, screenCfg)
      const out = tracker.update(a, screenCfg)
      lastScreenFrame = out.mode === 'cct'
        ? { mode: 'cct', kelvin: out.kelvin, brightness: out.brightness }
        : { mode: 'hsi', hue: out.hue, sat: out.sat, brightness: out.brightness }
      send(punched(lastScreenFrame), 'screen')
      if (now - lastPreview > 120) {
        lastPreview = now
        ctx.postMessage({ type: 'screen', analysis: a, out })
      }
      if (now - lastThumb > 350) {
        lastThumb = now
        const bitmap = canvas.transferToImageBitmap?.() ?? await createImageBitmap(canvas)
        ctx.postMessage({ type: 'screen-thumb', bitmap }, [bitmap])
      }
    }
    frame.close()
  }
  try { await reader.cancel() } catch { /* already closed */ }
  lastScreenFrame = null
  end('screen')
  ctx.postMessage({ type: 'screen-ended' })
}

// ---------------------------------------------------------------- control

ctx.onmessage = (e: MessageEvent) => {
  const m = e.data
  switch (m.type) {
    case 'init':
      url = m.url
      if (!ws) connect()
      break
    case 'config':
      if (m.audio) audioCfg = { ...audioCfg, ...m.audio }
      if (m.screen) screenCfg = { ...screenCfg, ...m.screen }
      if (m.rate) rate = m.rate
      if (m.light !== undefined && open.size === 0) target = m.light
      break
    case 'audio-port':
      audioPort?.close()
      audioPort = m.port as MessagePort
      audioCombo = Boolean(m.combo)
      Object.assign(audio, { peak: 0.01, bassPeak: 0.01, level: 0, history: [], beatIndex: 0, flash: 0 })
      if (!audioCombo) begin('audio')
      audioPort.onmessage = (ev: MessageEvent) => onBands(ev.data)
      break
    case 'video':
      void readScreen(m.readable)
      break
    case 'stop':
      if (m.what === 'audio') { audioPort?.close(); audioPort = null; if (!audioCombo) end('audio'); audioCombo = false }
      if (m.what === 'screen') { screenRunning = false; end('screen') }
      break
  }
}
