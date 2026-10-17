import type { LightState } from './types'

export type RGB = [number, number, number] // 0-1

export const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v)
export const lerp = (a: number, b: number, f: number) => a + (b - a) * f

export function kelvinToRgb(kelvin: number): RGB {
  const t = clamp(kelvin, 1000, 40000) / 100
  let r: number, g: number, b: number
  if (t <= 66) {
    r = 255
    g = 99.4708025861 * Math.log(t) - 161.1195681661
    b = t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307
  } else {
    r = 329.698727446 * Math.pow(t - 60, -0.1332047592)
    g = 288.1221695283 * Math.pow(t - 60, -0.0755148492)
    b = 255
  }
  return [clamp(r, 0, 255) / 255, clamp(g, 0, 255) / 255, clamp(b, 0, 255) / 255]
}

export function hsvToRgb(h: number, s: number, v = 100): RGB {
  const hh = (((h % 360) + 360) % 360) / 60
  const ss = s / 100
  const vv = v / 100
  const c = vv * ss
  const x = c * (1 - Math.abs((hh % 2) - 1))
  const m = vv - c
  const table: RGB[] = [[c, x, 0], [x, c, 0], [0, c, x], [0, x, c], [x, 0, c], [c, 0, x]]
  const [r, g, b] = table[Math.floor(hh) % 6]
  return [r + m, g + m, b + m]
}

export function rgbToHsv([r, g, b]: RGB): [number, number, number] {
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const d = max - min
  let h = 0
  if (d !== 0) {
    if (max === r) h = 60 * (((g - b) / d) % 6)
    else if (max === g) h = 60 * ((b - r) / d + 2)
    else h = 60 * ((r - g) / d + 4)
  }
  return [(h + 360) % 360, max === 0 ? 0 : (d / max) * 100, max * 100]
}

export function hexToRgb(hex: string): RGB {
  let t = hex.replace('#', '')
  if (t.length === 3) t = t.split('').map((c) => c + c).join('')
  const n = parseInt(t.slice(0, 6), 16)
  if (Number.isNaN(n)) return [0.5, 0.5, 0.5]
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255]
}

export function rgbToHex([r, g, b]: RGB): string {
  return '#' + [r, g, b].map((c) => Math.round(clamp(c, 0, 1) * 255).toString(16).padStart(2, '0')).join('')
}

export const rgbCss = ([r, g, b]: RGB, alpha = 1) =>
  `rgb(${Math.round(r * 255)} ${Math.round(g * 255)} ${Math.round(b * 255)} / ${alpha})`

export function isValidHex(v: string) {
  return /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.test(v.trim())
}

/** Green/magenta tint: positive pushes magenta (less green), negative pushes green. */
function tinted([r, g, b]: RGB, gm: number): RGB {
  const k = gm / 100
  return k >= 0
    ? [clamp(r * (1 + 0.08 * k), 0, 1), clamp(g * (1 - 0.32 * k), 0, 1), clamp(b * (1 + 0.1 * k), 0, 1)]
    : [clamp(r * (1 + 0.25 * k), 0, 1), clamp(g * (1 - 0.06 * k), 0, 1), clamp(b * (1 + 0.25 * k), 0, 1)]
}

/** The colour a state emits, at full brightness. Null when it has no fixed colour. */
export function stateColor(s: LightState): RGB | null {
  switch (s.mode) {
    case 'cct':
      return tinted(kelvinToRgb(s.cct.kelvin), s.cct.gm)
    case 'hsi':
      return hsvToRgb(s.hsi.hue, s.hsi.sat)
    case 'rgbw': {
      const { r, g, b, w } = s.rgbw
      const raw: RGB = [(r + w * 0.95) / 1000, (g + w * 0.9) / 1000, (b + w * 0.8) / 1000]
      const peak = Math.max(...raw, 0.001)
      return raw.map((c) => c / peak) as RGB
    }
    case 'gel':
      return s.gel ? hexToRgb(s.gel.hex) : null
    default:
      return null
  }
}

/** What the studio looks like lit by this state: colour plus a 0-1 intensity. */
export function emission(s: LightState): { rgb: RGB; level: number } {
  const rgb = stateColor(s) ?? kelvinToRgb(2900)
  const level = s.power ? Math.pow(clamp(s.brightness, 0, 100) / 100, 0.6) : 0
  return { rgb, level }
}

/** Relative luminance, for choosing readable text on a swatch. */
export function luminance([r, g, b]: RGB) {
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4))
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

export const inkOn = (rgb: RGB) => (luminance(rgb) > 0.45 ? '#16171a' : '#f4f4f2')

export function hueName(h: number): string {
  const names: [number, string][] = [
    [8, 'red'], [22, 'vermilion'], [38, 'orange'], [52, 'amber'], [66, 'yellow'], [90, 'chartreuse'],
    [150, 'green'], [172, 'jade'], [192, 'cyan'], [212, 'azure'], [245, 'blue'], [268, 'indigo'],
    [290, 'violet'], [318, 'magenta'], [340, 'pink'], [352, 'rose'], [361, 'red'],
  ]
  const hh = ((h % 360) + 360) % 360
  return names.find(([limit]) => hh < limit)?.[1] ?? 'red'
}

export function kelvinName(k: number): string {
  if (k < 2100) return 'Candlelight'
  if (k < 2700) return 'Sunrise'
  if (k < 3100) return 'Warm white'
  if (k < 3600) return 'Tungsten'
  if (k < 4500) return 'Neutral'
  if (k < 5300) return 'Morning sun'
  if (k < 6100) return 'Daylight'
  if (k < 7100) return 'Overcast'
  if (k < 8500) return 'Open shade'
  return 'Blue sky'
}
