// Mirrors service/gaffer: state.py, catalog.py, effects/base.py, fixture.py, hub.py.

export type Mode = 'cct' | 'hsi' | 'rgbw' | 'gel' | 'fx'

export interface Cct { kelvin: number; gm: number }
export interface Hsi { hue: number; sat: number }
export interface Rgbw { r: number; g: number; b: number; w: number }
export interface Gel { version: number; brand: number; number: number; sub_brand: number; label: string; hex: string }
export interface Fx { symbol: number; speed: number | null; params: Record<string, number> }

export interface LightState {
  power: boolean
  brightness: number
  mode: Mode
  cct: Cct
  hsi: Hsi
  rgbw: Rgbw
  gel: Gel | null
  fx: Fx | null
}

export type DeepPartial<T> = { [K in keyof T]?: T[K] extends object | null ? DeepPartial<NonNullable<T[K]>> | null : T[K] }
export type StatePatch = DeepPartial<LightState>

export interface ParamSpec {
  key: string
  label: string
  kind: 'number' | 'color' | 'kelvin' | 'palette' | 'choice' | 'bool' | 'option_value' | 'kelvin100' | 'text'
  default: unknown
  min?: number
  max?: number
  step?: number
  unit?: string
  options?: { value: string | number; label: string }[]
  hint?: string
  inferred?: boolean
}

export interface BuiltinEffect { symbol: number; name: string; params: ParamSpec[]; speed_max: number }

export type LightKind = 'rgb' | 'colour' | 'bicolour' | 'daylight' | 'unsupported'
export type GelSupport = 'native' | 'emulated' | 'white' | null

/** What a light can do, as switches: the UI shows a control only where its switch is on. */
export interface Features {
  white: boolean
  daylight: boolean
  colour: boolean
  channels: boolean
  tint: boolean
  gels: GelSupport
  builtin_effects: number
  fan: boolean
  battery: boolean
  smoothness: boolean
  control_modes: boolean
}

export interface Option { code: number; name: string }

export interface Caps {
  radio_id: string
  name: string
  chip: string
  min_kelvin: number
  max_kelvin: number
  gm_min: number
  gm_max: number
  has_tint: boolean
  modes: string[]
  effect_version: number
  effects: BuiltinEffect[]
  fan_modes: Option[]
  color_chip_version: number
  rgb_display: number
  rgb_channels: string[]
  battery: boolean
  smoothness_modes: Option[]
  control_modes: Option[]
  frequencies: Option[]
  brightness_steps: number
  note: string
  known: boolean
  /** Which driver commands this model, and what its maker is called ("Zhiyun"). */
  driver: string
  brand: string
  kind: LightKind
  kind_label: string
  features: Features
}

export interface GelChip extends Gel { series: string; family: string; how: 'native' | 'white' | 'colour' }

export interface SoftEffect {
  id: string
  name: string
  category: string
  description: string
  accent: string
  trigger: string
  params: ParamSpec[]
  /** Measured by running it: whether it uses colour, and whether its brightness moves. */
  colour: boolean
  brightness_moves: boolean
}

export interface EngineStatus {
  kind: 'effect' | 'transition' | 'timeline' | 'stream' | null
  effect: string | null
  label: string
  params: Record<string, unknown>
  elapsed: number
  duration: number | null
}

export type LinkPhase = 'idle' | 'scanning' | 'connecting' | 'connected' | 'backoff' | 'stopped' | 'no-light'

export interface LinkSnapshot {
  status: LinkPhase
  detail: string
  address: string | null
  /** The light the connection goes through; the others are reached by relay. */
  gateway: string | null
  connected_since: number | null
  latency_ms: number | null
  rssi: number | null
  sequence: number
  sequence_budget: number
  firmware: { mesh?: number; mcu?: string }
  interval_ms?: number | null
  source?: number | null
  demo?: boolean
}

export interface Readback {
  cct: { brightness: number; kelvin: number; gm: number } | null
  hsi: { brightness: number; hue: number; sat: number } | null
  heartbeat_at: number | null
  latency_ms: number | null
}

export interface PumpStats { sent: number; coalesced: number; skipped_identical: number; errors: number; rate: number }

export interface Settings {
  max_rate: number
  relay_ttl: number
  sync_interval: number
  default_fade: number
  favorites: string[]
  theme_accent: string
}

export type SyncProp = 'power' | 'brightness' | 'white' | 'colour' | 'effects'

export interface Group {
  id: string
  name: string
  members: string[]
  props: SyncProp[]
  enabled: boolean
}

export interface Battery { percent: number | null; hours?: number; minutes?: number; state?: number; at: number }

export interface Device {
  fan: number | null
  battery: Battery | null
  smoothness: number | null
  control: { mode: number; frequency: number } | null
}

/** One saved light, everything the studio knows about it. */
export interface LightView {
  id: string
  name: string
  address: string
  radio_id: string
  model: string
  kind: LightKind
  known_model: boolean
  model_source: 'advert' | 'manual' | 'unknown'
  node_address: number
  network: string
  added: number
  x: number | null
  y: number | null
  caps: Caps
  gel_key: string | null
  state: LightState
  source: string
  engine: EngineStatus
  readback: Readback
  device: Device
  reachable: boolean | null
  /** Another controller (the brand's own app) holds this light's one connection. */
  held: boolean
  online: boolean
}

export interface ModelRow { radio_id: string; name: string; kind: LightKind; kind_label: string }

/** `new` is a light of a brand with nothing to pair (Zhiyun, Yongnuo) that is not saved yet. */
export type Relation = 'saved' | 'unpaired' | 'your-network' | 'elsewhere' | 'new'

export interface Nearby {
  address: string
  name: string | null
  rssi: number | null
  radio_id: string | null
  model: string | null
  kind: LightKind | null
  relation: Relation
  light_id: string | null
  seen_at: number
  driver: string
  brand: string
  /** Adding it needs a channel (Yongnuo). Only set on `new` lights. */
  needs_channel?: boolean
}

export interface Pairing { address: string; step: 'starting' | 'provisioning' | 'binding' | 'bound' | 'done' | 'failed'; error: string; at: number }

export interface StoredItem { id: string; name: string; created?: number; updated?: number; [key: string]: unknown }

export interface Scene extends StoredItem { state?: LightState; effect?: string; params?: Record<string, unknown> }
export interface Preset extends StoredItem { effect: string; params: Record<string, unknown> }
export interface Keyframe { t: number; state: StatePatch; ease: string }
export interface Timeline extends StoredItem { keyframes: Keyframe[]; loop: boolean; duration: number }
export interface Schedule extends StoredItem {
  enabled: boolean
  at: string            // "HH:MM"
  days: number[]        // 0 = Monday
  action: 'scene' | 'effect' | 'sunrise' | 'off' | 'on'
  target?: string       // scene id or effect id
  minutes?: number
  lights?: string[]     // which lights; every light when empty
}
export interface Swatch extends StoredItem { hex: string }

export interface StoreSnapshot {
  settings: Settings
  scenes: Scene[]
  presets: Preset[]
  timelines: Timeline[]
  schedules: Schedule[]
  swatches: Swatch[]
}

export type Collection = 'scenes' | 'presets' | 'timelines' | 'schedules' | 'swatches'

export interface LogEntry { t: number; kind: string; text: string }

export interface LightsView {
  lights: LightView[]
  gel_tables: Record<string, GelChip[]>
  network: string | null
}

export interface Hello extends LightsView {
  type: 'hello'
  selected: string | null
  effects: SoftEffect[]
  models: ModelRow[]
  groups: Group[]
  link: LinkSnapshot
  store: StoreSnapshot
  log: LogEntry[]
  demo: boolean
  nearby: Nearby[]
  scanning: boolean
  pairing: Pairing | null
}

export type ServerMessage =
  | Hello
  | ({ type: 'lights' } & LightsView)
  | { type: 'state'; light: string; state: LightState; source: string }
  | { type: 'link'; link: LinkSnapshot }
  | { type: 'readback'; light: string; readback: Readback }
  | { type: 'heartbeat'; light: string; at: number }
  | { type: 'engine'; light: string; engine: EngineStatus }
  | { type: 'stats'; stats: { pump: PumpStats; link: LinkSnapshot; clients: number }; reachable: Record<string, boolean | null>; held?: Record<string, boolean> }
  | { type: 'log'; entry: LogEntry }
  | { type: 'toast'; kind: string; text: string }
  | { type: 'device'; light: string; device: Device }
  | { type: 'settings'; settings: Settings }
  | { type: 'store'; collection: Collection; items: StoredItem[] }
  | { type: 'groups'; groups: Group[] }
  | { type: 'nearby'; nearby: Nearby[]; scanning: boolean }
  | { type: 'pairing'; pairing: Pairing }
  | { type: 'placed'; light: string; x: number; y: number }
  | { type: 'selected'; light: string; rid?: number }
  | { type: 'error'; of?: string; text: string; rid?: number }
  | { type: 'ack'; of: string; rid?: number; [key: string]: unknown }
