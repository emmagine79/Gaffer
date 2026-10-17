import { create } from 'zustand'
import { Socket, socketUrl } from '../lib/socket'
import type {
  Caps, Collection, Device, EngineStatus, GelChip, Group, Hello, LightState, LightView, LightsView, LinkSnapshot,
  LogEntry, ModelRow, Nearby, Pairing, PumpStats, Readback, ServerMessage, Settings, SoftEffect, StatePatch,
  StoreSnapshot, StoredItem,
} from '../lib/types'

export type TabId =
  | 'live' | 'white' | 'colour' | 'gels' | 'effects' | 'timeline' | 'sync'
  | 'scenes' | 'schedule' | 'mesh' | 'device' | 'lab' | 'guide'

export interface Toast { id: number; text: string; kind: 'info' | 'error' | 'warn' | 'sync' | 'ok' }

const LEASE_MS = 350
const SELECTED_KEY = 'gaffer.selected'

/**
 * A stable empty list for selectors. Zustand compares selector results by
 * reference: `s.store?.scenes ?? []` would return a new array on every call
 * before the store loads, which React reads as endless change (error #185).
 */
export const EMPTY: never[] = []

/** Commands that act on one light: the store names the selected one on each. */
const LIGHT_SCOPED = new Set([
  'set', 'power', 'look.apply', 'engine.start', 'engine.params', 'engine.trigger', 'engine.stop', 'timeline.play',
  'stream.begin', 'stream.end', 'stream', 'fan', 'device.smoothness', 'device.control', 'readback', 'raw',
  'lab.frame', 'lab.record', 'scene.apply', 'store.upsert', 'group.match',
])

interface Studio {
  socketOpen: boolean
  ready: boolean
  demo: boolean

  // Every light, and the mesh around them
  lights: LightView[]
  selected: string | null
  gelTables: Record<string, GelChip[]>
  models: ModelRow[]
  groups: Group[]
  nearby: Nearby[]
  scanning: boolean
  pairing: Pairing | null
  network: string | null

  // The selected light, projected so every tab reads one light
  light: LightView | null
  caps: Caps | null
  gels: GelChip[]
  state: LightState | null
  source: string
  engine: EngineStatus
  readback: Readback | null
  device: Device

  effects: SoftEffect[]
  link: LinkSnapshot | null
  store: StoreSnapshot | null
  log: LogEntry[]
  pump: PumpStats | null
  toasts: Toast[]
  /** The look on now (SPEC-010), or null. */
  look: { id: string; name: string } | null
  /** The active cue (SPEC-014): steps run so far (0 is the top) out of steps, or null. */
  cue: { id: string; name: string; step: number; steps: number; next: { id: string; name: string } | null; blocked: string | null } | null
  tab: TabId
  connectionSheet: boolean
  addLight: boolean
  palette: boolean

  setTab: (tab: TabId) => void
  select: (id: string, opts?: { connect?: boolean }) => void
  moveLight: (id: string, x: number, y: number) => void
  apply: (patch: StatePatch, opts?: { fade?: number }) => void
  applyTo: (id: string, patch: StatePatch, opts?: { fade?: number }) => void
  /** Show a light at this level now, sending nothing: the server has already been told. */
  showLevel: (id: string, brightness: number) => void
  power: (on: boolean, fade?: number) => void
  powerOf: (id: string, on: boolean, fade?: number) => void
  send: (message: Record<string, unknown>) => void
  request: (message: Record<string, unknown>, timeoutMs?: number) => Promise<ServerMessage>
  upsert: (collection: Collection, item: Partial<StoredItem> & { name: string }) => Promise<StoredItem | null>
  remove: (collection: Collection, id: string) => void
  toast: (text: string, kind?: Toast['kind']) => void
  dismissToast: (id: number) => void
  setConnectionSheet: (open: boolean) => void
  setAddLight: (open: boolean) => void
  setPalette: (open: boolean) => void
}

const idleEngine: EngineStatus = { kind: null, effect: null, label: '', params: {}, elapsed: 0, duration: null }
const noDevice: Device = { fan: null, battery: null, smoothness: null, control: null }

function merge<T>(base: T, patch: unknown): T {
  if (patch === null || typeof patch !== 'object' || Array.isArray(patch)) return patch as T
  if (base === null || typeof base !== 'object') return patch as T
  const out: Record<string, unknown> = { ...(base as Record<string, unknown>) }
  for (const [k, v] of Object.entries(patch as Record<string, unknown>)) {
    out[k] = k === 'params' ? v : merge(out[k], v)
  }
  return out as T
}

/** The selected light's fields, lifted to the top of the store. */
function project(lights: LightView[], selected: string | null, gelTables: Record<string, GelChip[]>) {
  const light = lights.find((l) => l.id === selected) ?? null
  return {
    light,
    caps: light?.caps ?? null,
    gels: light?.gel_key ? gelTables[light.gel_key] ?? EMPTY : EMPTY,
    state: light?.state ?? null,
    source: light?.source ?? 'restored',
    engine: light?.engine ?? idleEngine,
    readback: light?.readback ?? null,
    device: light?.device ?? noDevice,
  }
}

function patchLight(lights: LightView[], id: string, update: Partial<LightView>): LightView[] {
  return lights.map((l) => (l.id === id ? { ...l, ...update } : l))
}

/**
 * A new list of lights, with the selected light's projection kept in step.
 * Every change to `lights` must go through here: components such as the mesh
 * inspector read `light` directly, and a stale copy freezes them.
 */
function withLights(selected: string | null, lights: LightView[]) {
  return { lights, light: lights.find((l) => l.id === selected) ?? null }
}

function rememberedSelection(lights: LightView[], fallback: string | null): string | null {
  let saved: string | null = null
  try { saved = localStorage.getItem(SELECTED_KEY) } catch { /* private mode */ }
  if (saved && lights.some((l) => l.id === saved)) return saved
  return fallback && lights.some((l) => l.id === fallback) ? fallback : lights[0]?.id ?? null
}

function remember(id: string | null) {
  try {
    if (id) localStorage.setItem(SELECTED_KEY, id)
  } catch { /* private mode */ }
}

const socket = new Socket(socketUrl())
let pendingPatch: StatePatch | null = null
let pendingFade = 0
let pendingLight: string | null = null
let frameQueued = false
let leaseUntil = 0
let leaseTimer = 0
/** The newest server state suppressed during a lease; applied when the lease ends. */
let stashed: { light: string; state: LightState; source: string } | null = null
let toastSeq = 0

function initialTab(): TabId {
  const hash = location.hash.replace('#', '') as TabId
  return hash || 'live'
}

function scoped(message: Record<string, unknown>): Record<string, unknown> {
  const selected = useStudio.getState().selected
  if (!LIGHT_SCOPED.has(String(message.type)) || message.light || !selected) return message
  return { ...message, light: selected }
}

export const useStudio = create<Studio>()((set, get) => ({
  socketOpen: false,
  ready: false,
  demo: false,

  lights: EMPTY,
  selected: null,
  gelTables: {},
  models: EMPTY,
  groups: EMPTY,
  nearby: EMPTY,
  scanning: false,
  pairing: null,
  network: null,

  light: null,
  caps: null,
  gels: EMPTY,
  state: null,
  source: 'restored',
  engine: idleEngine,
  readback: null,
  device: noDevice,

  effects: EMPTY,
  link: null,
  store: null,
  log: EMPTY,
  pump: null,
  toasts: EMPTY,
  look: null,
  cue: null,
  tab: initialTab(),
  connectionSheet: false,
  addLight: false,
  palette: false,

  setTab: (tab) => {
    history.replaceState(null, '', `#${tab}`)
    set({ tab })
  },

  select: (id, opts) => {
    // connect: move the Bluetooth link to this light's network if it is on another
    // one. Only explicit choices ask for that; looking at a light never does.
    const connect = Boolean(opts?.connect)
    if (id === get().selected) {
      if (connect) socket.send({ type: 'select', light: id, connect })
      return
    }
    settleSelection()
    remember(id)
    set((s) => ({ selected: id, ...project(s.lights, id, s.gelTables) }))
    socket.send({ type: 'select', light: id, connect })
  },

  moveLight: (id, x, y) => {
    set((s) => withLights(s.selected, patchLight(s.lights, id, { x, y })))
    socket.send({ type: 'lights.place', light: id, x, y })
  },

  apply: (patch, opts) => {
    const { state: current, selected } = get()
    if (!current || !selected) return
    // Optimistic: the UI moves now; the server confirms later.
    leaseUntil = performance.now() + LEASE_MS
    const next = merge(current, patch)
    set((s) => ({ state: next, source: 'app', ...withLights(s.selected, patchLight(s.lights, selected, { state: next })) }))
    pendingPatch = pendingPatch ? merge(pendingPatch, patch) : patch
    pendingLight = selected
    pendingFade = opts?.fade ?? 0
    if (pendingFade > 0) {
      flush()
      return
    }
    if (!frameQueued) {
      frameQueued = true
      // One send per frame while visible. Hidden tabs get no animation frames
      // at all, so fall back to a macrotask there or the patch would wait forever.
      if (document.visibilityState === 'hidden') window.setTimeout(flush, 0)
      else requestAnimationFrame(flush)
    }
  },

  applyTo: (id, patch, opts) => {
    if (id === get().selected) {
      get().apply(patch, opts)
      return
    }
    const light = get().lights.find((l) => l.id === id)
    if (light) set((s) => withLights(s.selected, patchLight(s.lights, id, { state: merge(light.state, patch) })))
    socket.send({ type: 'set', light: id, patch, fade: opts?.fade ?? 0 })
  },

  showLevel: (id, brightness) => {
    const light = get().lights.find((l) => l.id === id)
    if (!light) return
    const next = { ...light.state, brightness }
    set((s) => ({ ...withLights(s.selected, patchLight(s.lights, id, { state: next })), ...(id === s.selected ? { state: next } : {}) }))
  },

  power: (on, fade = 0) => {
    const { state: current, selected } = get()
    if (!selected) return
    flush() // a slider change still waiting for its frame must not land after this
    if (current) {
      const next = { ...current, power: on }
      set((s) => ({ state: next, ...withLights(s.selected, patchLight(s.lights, selected, { state: next })) }))
    }
    leaseUntil = performance.now() + LEASE_MS
    socket.send({ type: 'power', light: selected, on, fade })
  },

  powerOf: (id, on, fade = 0) => {
    flush()
    if (id === get().selected) {
      get().power(on, fade)
      return
    }
    const light = get().lights.find((l) => l.id === id)
    if (light) set((s) => withLights(s.selected, patchLight(s.lights, id, { state: { ...light.state, power: on } })))
    socket.send({ type: 'power', light: id, on, fade })
  },

  send: (message) => {
    // A slider change still waiting for its frame must not land after an effect starts: a late `set` cancels it.
    if (message.type === 'engine.start') flush()
    socket.send(scoped(message))
  },
  request: (message, timeoutMs) => socket.request(scoped(message), timeoutMs),

  upsert: async (collection, item) => {
    try {
      const reply = await socket.request(scoped({ type: 'store.upsert', collection, item }))
      return (reply as { item?: StoredItem }).item ?? null
    } catch (err) {
      get().toast((err as Error).message, 'error')
      return null
    }
  },

  remove: (collection, id) => socket.send({ type: 'store.delete', collection, id }),

  toast: (text, kind = 'info') => {
    const id = ++toastSeq
    set((s) => ({ toasts: [...s.toasts.slice(-3), { id, text, kind }] }))
    window.setTimeout(() => get().dismissToast(id), kind === 'error' || kind === 'warn' ? 6000 : 3200)
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  setConnectionSheet: (open) => set({ connectionSheet: open }),
  setAddLight: (open) => set({ addLight: open }),
  setPalette: (open) => set({ palette: open }),
}))

/**
 * Leave the light being edited cleanly: send what is still waiting for it, and
 * give it the server's last word if an echo was being held back by the lease.
 */
function settleSelection() {
  flush()
  const held = stashed
  stashed = null
  leaseUntil = 0
  if (held) updateLight(held.light, { state: held.state, source: held.source })
}

function flush() {
  frameQueued = false
  if (!pendingPatch) return
  socket.send({ type: 'set', light: pendingLight, patch: pendingPatch, fade: pendingFade })
  pendingPatch = null
  pendingFade = 0
}

/** New lights, removed lights, renamed or recognised lights: take the server's whole view. */
function takeLights(view: LightsView, preferred: string | null) {
  const set = useStudio.setState
  const s = useStudio.getState()
  const keep = view.lights.some((l) => l.id === s.selected)
  const selected = keep ? s.selected : rememberedSelection(view.lights, preferred)
  if (!keep) {
    settleSelection()
    remember(selected)
  }
  // While a slider is being dragged, keep showing the dragged value: the server's
  // copy in this refresh predates the drag.
  const leased = keep && leaseUntil > performance.now()
  const lights = leased ? view.lights.map((l) => (l.id === selected && s.state ? { ...l, state: s.state } : l)) : view.lights
  set({ lights, gelTables: view.gel_tables, network: view.network, selected, ...project(lights, selected, view.gel_tables) })
  if (selected && selected !== s.selected) socket.send({ type: 'select', light: selected })
}

/** Update one light; mirror it to the top of the store when it is the selected one. */
function updateLight(id: string, update: Partial<LightView>) {
  useStudio.setState((s) => {
    const lights = patchLight(s.lights, id, update)
    if (id !== s.selected) return { lights }
    const top: Partial<Studio> = withLights(s.selected, lights)
    if (update.engine) top.engine = update.engine
    if (update.readback) top.readback = update.readback
    if (update.device) top.device = update.device
    if (update.state) { top.state = update.state; top.source = update.source ?? s.source }
    return top
  })
}

function handle(m: ServerMessage) {
  const set = useStudio.setState
  switch (m.type) {
    case 'hello': {
      const h = m as Hello
      // A reconnect keeps this tab's own choice; storage is shared by every tab,
      // so it only decides on a first load.
      const mine = useStudio.getState().selected
      const selected = mine && h.lights.some((l) => l.id === mine) ? mine : rememberedSelection(h.lights, h.selected)
      leaseUntil = 0
      stashed = null
      remember(selected)
      set({
        ready: true, demo: h.demo, effects: h.effects, link: h.link, store: h.store, log: h.log, models: h.models,
        look: h.look && h.look_id ? { id: h.look_id, name: h.look } : null,
        groups: h.groups, nearby: h.nearby, scanning: h.scanning, pairing: h.pairing,
        lights: h.lights, gelTables: h.gel_tables, network: h.network, selected,
        ...project(h.lights, selected, h.gel_tables),
      })
      if (selected && selected !== h.selected) socket.send({ type: 'select', light: selected })
      break
    }
    case 'lights':
      takeLights(m, null)
      break
    case 'state': {
      const { selected } = useStudio.getState()
      if (m.light === selected) {
        const remaining = leaseUntil - performance.now()
        if (remaining > 0 && m.source === 'app') {
          // An echo of input still in flight: hold it, so the slider does not
          // jump back, but reconcile with it once the lease ends.
          stashed = { light: m.light, state: m.state, source: m.source }
          window.clearTimeout(leaseTimer)
          leaseTimer = window.setTimeout(() => {
            if (stashed && stashed.light === useStudio.getState().selected && performance.now() >= leaseUntil) {
              updateLight(stashed.light, { state: stashed.state, source: stashed.source })
            }
            stashed = null
          }, remaining + 20)
          break
        }
        stashed = null
      }
      updateLight(m.light, { state: m.state, source: m.source })
      break
    }
    case 'link':
      set({ link: m.link })
      break
    case 'readback':
      updateLight(m.light, { readback: m.readback })
      break
    case 'heartbeat': {
      const light = useStudio.getState().lights.find((l) => l.id === m.light)
      if (light) updateLight(m.light, { readback: { ...light.readback, heartbeat_at: m.at }, reachable: true })
      break
    }
    case 'engine':
      updateLight(m.light, { engine: m.engine })
      break
    case 'stats': {
      set({ pump: m.stats.pump, link: m.stats.link })
      const lights = useStudio.getState().lights
      const heldNow = (id: string) => m.held?.[id] ?? false
      const maxNow = (id: string) => m.max_mode?.[id] ?? null
      const changed = lights.some((l) => (m.reachable[l.id] ?? null) !== l.reachable || heldNow(l.id) !== l.held || maxNow(l.id) !== l.max_mode)
      if (changed) set((s) => withLights(s.selected, s.lights.map((l) => ({ ...l, reachable: m.reachable[l.id] ?? null, held: heldNow(l.id), max_mode: maxNow(l.id) }))))
      break
    }
    case 'log':
      set((s) => ({ log: [...s.log.slice(-299), m.entry] }))
      break
    case 'toast':
      useStudio.getState().toast(m.text, m.kind === 'sync' || m.kind === 'error' || m.kind === 'warn' ? m.kind : 'info')
      break
    case 'device':
      updateLight(m.light, { device: m.device })
      break
    case 'settings':
      set((s) => ({ store: s.store ? { ...s.store, settings: m.settings as Settings } : s.store }))
      break
    case 'look':
      set({ look: m.id && m.name ? { id: m.id, name: m.name } : null })
      break
    case 'cue':
      set({ cue: m.id && m.name && m.step !== null && m.steps !== null ? { id: m.id, name: m.name, step: m.step, steps: m.steps, next: m.next, blocked: m.blocked ?? null } : null })
      break
    case 'store':
      set((s) => ({ store: s.store ? { ...s.store, [m.collection]: m.items } : s.store }))
      break
    case 'groups':
      set({ groups: m.groups })
      break
    case 'nearby':
      set({ nearby: m.nearby, scanning: m.scanning })
      break
    case 'pairing':
      set({ pairing: m.pairing })
      break
    case 'placed':
      set((s) => withLights(s.selected, patchLight(s.lights, m.light, { x: m.x, y: m.y })))
      break
    case 'error':
      if (m.of === 'set' && stashed) {
        // The server refused the change: show what it actually has.
        updateLight(stashed.light, { state: stashed.state, source: stashed.source })
        stashed = null
      }
      if (m.rid === undefined) useStudio.getState().toast(m.text, 'error')
      break
  }
}

const sendVisibility = () => socket.send({ type: 'visibility', visible: document.visibilityState === 'visible' })

socket.onMessage(handle)
socket.onStatus((open) => {
  useStudio.setState({ socketOpen: open })
  if (open) sendVisibility() // a fresh server-side client assumes "visible"
})
socket.connect()

document.addEventListener('visibilitychange', () => {
  // A patch waiting for an animation frame would wait forever once hidden.
  if (document.visibilityState === 'hidden' && frameQueued) flush()
  sendVisibility()
})
