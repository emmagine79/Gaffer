import { describe, expect, it } from 'vitest'
import { AmbientTracker, analyse, type AmbientConfig } from './ambient'

const W = 64
const H = 36

type Fill = (x: number, y: number) => [number, number, number]

function frame(fill: Fill): Uint8ClampedArray {
  const d = new Uint8ClampedArray(W * H * 4)
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const [r, g, b] = fill(x, y)
      const i = (y * W + x) * 4
      d[i] = r; d[i + 1] = g; d[i + 2] = b; d[i + 3] = 255
    }
  }
  return d
}

const match: AmbientConfig = { style: 'match', zone: 'whole', whites: true, warmth: 0 }
const mood: AmbientConfig = { ...match, style: 'mood' }

describe('analyse', () => {
  it('a mostly white scene with a small red logo reads as white, not red', () => {
    const f = frame((x, y) => (x < 8 && y < 6 ? [230, 20, 20] : [235, 235, 235]))
    const a = analyse(f, W, H, match)
    expect(a.mode).toBe('cct')
    expect(a.kelvin).toBeGreaterThan(5500)
    expect(a.kelvin).toBeLessThan(7500)
  })

  it('mood style chases the vivid logo instead', () => {
    const f = frame((x, y) => (x < 8 && y < 6 ? [230, 20, 20] : [235, 235, 235]))
    const a = analyse(f, W, H, mood)
    expect(a.mode).toBe('hsi')
    expect(Math.min(a.hue, 360 - a.hue)).toBeLessThan(15)
  })

  it('half red, half blue picks one of them, never a muddy purple', () => {
    const f = frame((x) => (x < 34 ? [10, 30, 220] : [220, 20, 20]))
    const a = analyse(f, W, H, match)
    expect(a.mode).toBe('hsi')
    const nearBlue = Math.abs(a.hue - 230) < 20
    const nearRed = Math.min(a.hue, 360 - a.hue) < 20
    expect(nearBlue || nearRed).toBe(true)
    expect(a.sat).toBeGreaterThan(70)
  })

  it('black letterbox bars do not darken or desaturate the picture', () => {
    const bars = frame((_x, y) => (y < 7 || y >= 29 ? [0, 0, 0] : [20, 140, 210]))
    const full = frame(() => [20, 140, 210])
    const a = analyse(bars, W, H, match)
    const b = analyse(full, W, H, match)
    expect(Math.abs(a.hue - b.hue)).toBeLessThan(3)
    expect(a.luminance).toBeCloseTo(b.luminance, 1)
  })

  it('a candlelit, warm low-saturation scene becomes warm white', () => {
    const f = frame(() => [205, 165, 120])
    const a = analyse(f, W, H, match)
    expect(a.mode).toBe('cct')
    expect(a.kelvin).toBeLessThan(4200)
  })

  it('zones look only at their part of the screen', () => {
    const f = frame((x) => (x < 16 ? [20, 200, 40] : [200, 30, 160]))
    expect(Math.abs(analyse(f, W, H, { ...match, zone: 'left' }).hue - 128)).toBeLessThan(20)
    expect(Math.abs(analyse(f, W, H, { ...match, zone: 'right' }).hue - 311)).toBeLessThan(20)
  })

  it('warmth shifts the white it chooses', () => {
    const f = frame(() => [235, 235, 235])
    const neutral = analyse(f, W, H, match)
    const warmer = analyse(f, W, H, { ...match, warmth: -1500 })
    expect(warmer.kelvin).toBeLessThan(neutral.kelvin - 1000)
  })

  it('reports a palette of what it found, largest first', () => {
    const f = frame((x) => (x < 48 ? [20, 60, 200] : [230, 120, 20]))
    const a = analyse(f, W, H, match)
    expect(a.palette.length).toBeGreaterThanOrEqual(2)
    expect(a.palette[0].share).toBeGreaterThan(a.palette[1].share)
  })
})

describe('AmbientTracker', () => {
  const base = { mode: 'hsi' as const, hue: 200, sat: 80, kelvin: 6500, luminance: 0.6, palette: [], chromaShare: 0.8 }

  it('glides between similar frames', () => {
    const t = new AmbientTracker()
    t.update(base, { smooth: 0.6, low: 0, high: 100 })
    const out = t.update({ ...base, hue: 215 }, { smooth: 0.6, low: 0, high: 100 })
    expect(out.hue).toBeGreaterThan(200)
    expect(out.hue).toBeLessThan(215)
  })

  it('snaps on a scene cut', () => {
    const t = new AmbientTracker()
    t.update(base, { smooth: 0.9, low: 0, high: 100 })
    const out = t.update({ ...base, hue: 20, luminance: 0.2 }, { smooth: 0.9, low: 0, high: 100 })
    expect(out.hue).toBeCloseTo(20, 0)
  })

  it('does not flip between white and colour on every borderline frame', () => {
    const t = new AmbientTracker()
    t.update(base, { smooth: 0.3, low: 0, high: 100 })
    const white = { ...base, mode: 'cct' as const, sat: 12, chromaShare: 0.3 }
    expect(t.update(white, { smooth: 0.3, low: 0, high: 100 }).mode).toBe('hsi')
    t.update(white, { smooth: 0.3, low: 0, high: 100 })
    expect(t.update(white, { smooth: 0.3, low: 0, high: 100 }).mode).toBe('cct')
  })

  it('maps scene brightness into the chosen range', () => {
    const t = new AmbientTracker()
    const out = t.update({ ...base, luminance: 0 }, { smooth: 0, low: 10, high: 80 })
    expect(out.brightness).toBeCloseTo(10, 0)
  })
})
