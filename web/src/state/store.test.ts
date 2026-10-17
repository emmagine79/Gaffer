// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Caps, LightState, LightView } from '../lib/types'

// The store opens a WebSocket on import; give it one that goes nowhere.
class SilentSocket {
  static OPEN = 1
  static made: SilentSocket[] = []
  readyState = 0
  constructor() { SilentSocket.made.push(this) }
  onopen: (() => void) | null = null
  onmessage: ((e: MessageEvent) => void) | null = null
  onclose: (() => void) | null = null
  sent: string[] = []
  send(data: string) { this.sent.push(data) }
  close() {}
}
vi.stubGlobal('WebSocket', SilentSocket)

const { useStudio } = await import('./store')

const state = (brightness: number): LightState => ({
  power: true, brightness, mode: 'cct', cct: { kelvin: 5600, gm: 0 }, hsi: { hue: 0, sat: 100 },
  rgbw: { r: 0, g: 0, b: 0, w: 0 }, gel: null, fx: null,
})

function light(id: string, brightness: number): LightView {
  return {
    id, name: id, address: id, radio_id: '008F', model: 'ML100R', kind: 'rgb', known_model: true,
    model_source: 'advert', node_address: 2, network: 'n', added: 0, x: null, y: null,
    caps: { features: {} } as unknown as Caps, gel_key: null, state: state(brightness), source: 'app',
    engine: { kind: null, effect: null, label: '', params: {}, elapsed: 0, duration: null },
    readback: { cct: null, hsi: null, heartbeat_at: null, latency_ms: null },
    device: { fan: null, battery: null, smoothness: null, control: null },
    reachable: true, online: true,
  }
}

describe('the selected light stays in step with every change', () => {
  beforeEach(() => {
    const lights = [light('key', 10), light('fill', 30)]
    useStudio.setState({ lights, selected: 'key', light: lights[0], state: lights[0].state })
  })

  it('moves the selected light when the master fader moves', () => {
    useStudio.getState().apply({ brightness: 49 })
    const s = useStudio.getState()
    expect(s.state?.brightness).toBe(49)
    expect(s.light?.state.brightness).toBe(49) // the mesh inspector reads this
    expect(s.lights.find((l) => l.id === 'key')?.state.brightness).toBe(49)
  })

  it('moves the selected light when it is driven from the mesh', () => {
    useStudio.getState().applyTo('key', { brightness: 64 })
    expect(useStudio.getState().light?.state.brightness).toBe(64)
  })

  it('changes another light without touching the selected one', () => {
    useStudio.getState().applyTo('fill', { brightness: 77 })
    const s = useStudio.getState()
    expect(s.lights.find((l) => l.id === 'fill')?.state.brightness).toBe(77)
    expect(s.light?.state.brightness).toBe(10)
  })

  it('switches power through the same path', () => {
    useStudio.getState().power(false)
    expect(useStudio.getState().light?.state.power).toBe(false)
  })

  it('follows a light that is selected afterwards', () => {
    useStudio.getState().select('fill')
    useStudio.getState().apply({ brightness: 5 })
    const s = useStudio.getState()
    expect(s.light?.id).toBe('fill')
    expect(s.light?.state.brightness).toBe(5)
  })
})

describe('selection and ordering survive reconnects and quick input', () => {
  const ws = () => SilentSocket.made[SilentSocket.made.length - 1]
  const sent = () => ws().sent.map((m) => JSON.parse(m) as { type: string; light?: string })

  beforeEach(() => {
    const lights = [light('key', 10), light('fill', 30)]
    useStudio.setState({ lights, selected: 'key', light: lights[0], state: lights[0].state })
    ws().readyState = 1
    ws().sent = []
  })

  it('keeps this tab on its own light when the studio says hello again', () => {
    useStudio.getState().select('fill')
    localStorage.setItem('lumen.selected', 'key') // another tab chose the key light meanwhile
    const hello = { type: 'hello', selected: 'key', lights: [light('key', 10), light('fill', 30)], gel_tables: {}, network: 'n',
      effects: [], models: [], groups: [], link: null, store: null, log: [], demo: true, nearby: [], scanning: false, pairing: null }
    ws().onmessage?.({ data: JSON.stringify(hello) } as MessageEvent)
    expect(useStudio.getState().selected).toBe('fill')
  })

  it('sends a waiting slider change before a power switch', () => {
    useStudio.getState().apply({ brightness: 60 })
    useStudio.getState().power(false)
    const kinds = sent().filter((m) => m.type === 'set' || m.type === 'power').map((m) => m.type)
    expect(kinds).toEqual(['set', 'power'])
  })

  it('sends a waiting change to the light it was made on, even after switching', () => {
    useStudio.getState().apply({ brightness: 61 })
    useStudio.getState().select('fill')
    const set = sent().find((m) => m.type === 'set')
    expect(set?.light).toBe('key')
  })

  it('moves the link only when asked', () => {
    useStudio.getState().select('fill')
    useStudio.getState().select('fill', { connect: true })
    const selects = sent().filter((m) => m.type === 'select') as { connect?: boolean }[]
    expect(selects.map((m) => m.connect)).toEqual([false, true])
  })
})
