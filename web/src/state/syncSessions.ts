import { create } from 'zustand'
import { AmbientTracker, analyse, type Style, type Zone } from '../lib/ambient'
import { canProcessTracks, startAudio, startScreen, streamWorker, type AudioSession } from '../lib/streamClient'
import type { LightView } from '../lib/types'
import { useStudio } from './store'

/**
 * Music and screen sync sessions, owned here rather than by the Sync tab so
 * they keep running while you use the rest of the studio.
 *
 * Each start bumps a generation; anything that resolves after a newer start or
 * a stop (a permission prompt answered late, a double click) cleans itself up
 * instead of leaving an orphaned capture driving the light. The two sources are
 * mutually exclusive. When something else takes the light over, capture stops
 * here without sending a stop of its own, so the takeover stands.
 */

export type Phase = 'idle' | 'starting' | 'running'

export interface MusicConfig { mode: 'pulse' | 'beat' | 'spectrum' | 'strobe'; sensitivity: number; smoothing: number; floor: number; ceiling: number; palette: string[] }
export interface ScreenConfig {
  style: Style        // match: what the room would look like; mood: the most vivid colour
  zone: Zone
  whites: boolean     // neutral scenes become true white
  warmth: number      // kelvin offset for those whites
  low: number
  high: number
  smooth: number
  withAudio: boolean  // also take the shared tab's sound
  punch: number       // how much the sound lifts the light
}

interface SyncSessions {
  music: Phase
  screen: Phase
  /** The light the running session drives. */
  target: string | null
  musicConfig: MusicConfig
  screenConfig: ScreenConfig
  setMusicConfig: (patch: Partial<MusicConfig>) => void
  setScreenConfig: (patch: Partial<ScreenConfig>) => void
  startMusic: (from: 'mic' | 'tab') => Promise<void>
  stopMusic: () => void
  startScreen: () => Promise<void>
  stopScreen: () => void
}

let musicGen = 0
let screenGen = 0
let audio: AudioSession | null = null
let stopScreenCapture: (() => void) | null = null
let comboAudio: AudioSession | null = null

export const analyser = () => audio?.analyser ?? null

const toast = (text: string) => useStudio.getState().toast(text, 'error')

/** Hand the worker the current settings; a session starting also fixes the light it drives. */
function postConfig(target?: string | null) {
  const s = useSync.getState()
  const rate = useStudio.getState().store?.settings.max_rate ?? 40
  const light = target !== undefined ? { light: target } : {}
  if (target !== undefined) useSync.setState({ target })
  streamWorker().postMessage({ type: 'config', audio: s.musicConfig, screen: s.screenConfig, rate, ...light })
}

export const useSync = create<SyncSessions>()((set, get) => ({
  music: 'idle',
  screen: 'idle',
  target: null,
  musicConfig: { mode: 'pulse', sensitivity: 0.6, smoothing: 0.5, floor: 4, ceiling: 100, palette: ['#ff006e', '#ffbe0b', '#3a86ff', '#8338ec', '#06d6a0'] },
  screenConfig: { style: 'match', zone: 'whole', whites: true, warmth: 0, low: 6, high: 85, smooth: 0.45, withAudio: false, punch: 0.5 },

  setMusicConfig: (patch) => set((s) => ({ musicConfig: { ...s.musicConfig, ...patch } })),
  setScreenConfig: (patch) => set((s) => ({ screenConfig: { ...s.screenConfig, ...patch } })),

  startMusic: async (from) => {
    if (get().music !== 'idle') return
    get().stopScreen()
    const target = useStudio.getState().selected // the light chosen when the button was pressed
    const gen = ++musicGen
    set({ music: 'starting' })
    try {
      const media = from === 'mic'
        ? await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } })
        : await navigator.mediaDevices.getDisplayMedia({ audio: true, video: true })
      media.getVideoTracks().forEach((t) => t.stop())
      if (gen !== musicGen) { media.getTracks().forEach((t) => t.stop()); return }
      if (!media.getAudioTracks().length) {
        media.getTracks().forEach((t) => t.stop())
        toast('No audio came through. When sharing, tick "Share tab audio" or "Share system audio".')
        set({ music: 'idle' })
        return
      }
      postConfig(target)
      const session = await startAudio(media)
      if (gen !== musicGen) { session.stop(); return }
      audio = session
      media.getAudioTracks()[0]?.addEventListener('ended', () => { if (gen === musicGen) get().stopMusic() })
      set({ music: 'running' })
    } catch (err) {
      if (gen !== musicGen) return
      const e = err as Error
      if (e.name === 'NotAllowedError') toast('Permission was refused, so nothing is listening')
      else toast(e.message)
      set({ music: 'idle' })
    }
  },

  stopMusic: () => {
    musicGen++
    audio?.stop() // the worker closes the session on its own socket, after its last frame
    audio = null
    set({ music: 'idle' })
  },

  startScreen: async () => {
    if (get().screen !== 'idle') return
    get().stopMusic()
    const target = useStudio.getState().selected
    const gen = ++screenGen
    set({ screen: 'starting' })
    try {
      const withAudio = get().screenConfig.withAudio
      const media = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 30 }, audio: withAudio })
      if (gen !== screenGen) { media.getTracks().forEach((t) => t.stop()); return }
      media.getVideoTracks()[0]?.addEventListener('ended', () => { if (gen === screenGen) get().stopScreen() })
      const audioTracks = media.getAudioTracks()
      const video = new MediaStream(media.getVideoTracks())
      postConfig(target)
      if (withAudio && audioTracks.length) {
        // The sound adds punch to the screen's colour rather than driving the light itself.
        const session = await startAudio(new MediaStream(audioTracks), { combo: true })
        if (gen !== screenGen) { session.stop(); video.getTracks().forEach((t) => t.stop()); return }
        comboAudio = session
      } else if (withAudio) {
        useStudio.getState().toast('No sound came with the share. Tick "Share tab audio" to add punch from it.', 'info')
      }
      stopScreenCapture = canProcessTracks ? startScreen(video) : mainThreadScreen(video, target)
      set({ screen: 'running' })
    } catch (err) {
      if (gen !== screenGen) return
      const e = err as Error
      if (e.name !== 'NotAllowedError') toast(e.message)
      set({ screen: 'idle' })
    }
  },

  stopScreen: () => {
    screenGen++
    comboAudio?.stop()
    comboAudio = null
    stopScreenCapture?.()
    stopScreenCapture = null
    set({ screen: 'idle' })
  },
}))

/** Browsers without MediaStreamTrackProcessor: the same analysis on the main thread (throttled when hidden). */
function mainThreadScreen(media: MediaStream, light: string | null): () => void {
  const { send } = useStudio.getState() // this session keeps to the light it started on
  const video = document.createElement('video')
  video.muted = true
  video.srcObject = media
  void video.play()
  const canvas = document.createElement('canvas')
  canvas.width = 64
  canvas.height = 36
  const g = canvas.getContext('2d', { willReadFrequently: true })
  const tracker = new AmbientTracker()
  send({ type: 'stream.begin', source: 'screen', light })
  const timer = window.setInterval(() => {
    if (!g || video.readyState < 2) return
    const cfg = useSync.getState().screenConfig // read live: no stale closure
    g.drawImage(video, 0, 0, 64, 36)
    const out = tracker.update(analyse(g.getImageData(0, 0, 64, 36).data, 64, 36, cfg), cfg)
    const frame = out.mode === 'cct'
      ? { mode: 'cct', kelvin: out.kelvin, brightness: out.brightness }
      : { mode: 'hsi', hue: out.hue, sat: out.sat, brightness: out.brightness }
    send({ type: 'stream', source: 'screen', frame, light })
  }, 40)
  return () => {
    window.clearInterval(timer)
    media.getTracks().forEach((t) => t.stop())
    send({ type: 'stream.end', source: 'screen', light })
  }
}

/** Keep the worker's configuration in step, and yield when something else takes the light. */
export function startSyncSessions() {
  const offConfig = useSync.subscribe((s, prev) => {
    const live = s.music !== 'idle' || s.screen !== 'idle'
    if (live && (s.musicConfig !== prev.musicConfig || s.screenConfig !== prev.screenConfig)) postConfig()
  })
  const offRate = useStudio.subscribe((s, prev) => {
    const rate = s.store?.settings.max_rate
    const sync = useSync.getState()
    if (rate && rate !== prev.store?.settings.max_rate && (sync.music !== 'idle' || sync.screen !== 'idle')) postConfig()
  })
  let sawStream = false
  // Watch the light the session drives, not the one being edited: selecting
  // another light is not a takeover.
  const kindOf = (lights: LightView[]) =>
    lights.find((l) => l.id === useSync.getState().target)?.engine.kind ?? null
  const offYield = useStudio.subscribe((s, prev) => {
    const kind = kindOf(s.lights)
    if (kind === kindOf(prev.lights)) return
    const sync = useSync.getState()
    const active = sync.music === 'running' || sync.screen === 'running'
    if (!active) { sawStream = false; return }
    if (kind === 'stream') sawStream = true
    else if (sawStream) {
      // Taken over (an effect, a scene, a fade): stop listening locally and let it stand.
      sawStream = false
      if (sync.music === 'running') sync.stopMusic()
      if (sync.screen === 'running') sync.stopScreen()
    }
  })
  return () => { offConfig(); offRate(); offYield() }
}
