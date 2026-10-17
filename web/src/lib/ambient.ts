/**
 * Screen colour to light colour, the way an ambilight should do it. Pure.
 *
 * What it fixes over a plain average:
 *
 * - **Dominant, not mean.** Pixels are binned by hue and the most covered
 *   colour wins, so red and blue halves give red or blue, never a muddy purple.
 * - **Real light.** Colours are averaged in linear light, not gamma-encoded
 *   values, so mixes are as bright as they look.
 * - **Whites are whites.** Neutral scenes, and the warm low-saturation tones
 *   of skin, paper and lamplight, become the light's true high-CRI white at a
 *   matched colour temperature instead of a washed-out colour.
 * - **Bars ignored.** Black letterbox and pillarbox bars are trimmed before
 *   anything is measured.
 * - **Zones.** Follow the whole screen, one edge, or the border, ambilight style.
 */

export type Zone = 'whole' | 'left' | 'right' | 'top' | 'bottom' | 'edges' | 'centre'
export type Style = 'match' | 'mood'

export interface AmbientConfig {
  style: Style
  zone: Zone
  whites: boolean   // allow true white for neutral scenes
  warmth: number    // kelvin offset applied to chosen whites
}

export interface Analysis {
  mode: 'cct' | 'hsi'
  hue: number        // 0-360
  sat: number        // 0-100
  kelvin: number     // 1800-10000
  luminance: number  // 0-1, perceptual (CIE L*)
  palette: { hex: string; share: number }[]
  chromaShare: number
}

const LINEAR = Array.from({ length: 256 }, (_, i) => {
  const c = i / 255
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
})

const toSrgb = (c: number) => {
  const v = c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055
  return Math.max(0, Math.min(1, v))
}

function hsv(r: number, g: number, b: number): [number, number, number] {
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const d = max - min
  let h = 0
  if (d > 0) {
    if (max === r) h = 60 * (((g - b) / d) % 6)
    else if (max === g) h = 60 * ((b - r) / d + 2)
    else h = 60 * ((r - g) / d + 4)
  }
  return [(h + 360) % 360, max === 0 ? 0 : d / max, max]
}

const hex = (r: number, g: number, b: number) =>
  '#' + [r, g, b].map((c) => Math.round(toSrgb(c) * 255).toString(16).padStart(2, '0')).join('')

/** Warm hues tolerate more saturation before they stop reading as white. */
function isNeutral(h: number, s: number) {
  const warm = h >= 15 && h <= 55
  return s < (warm ? 0.45 : 0.22)
}

/** McCamy's approximation, from linear sRGB. */
function kelvinOf(r: number, g: number, b: number): number {
  const X = 0.4124 * r + 0.3576 * g + 0.1805 * b
  const Y = 0.2126 * r + 0.7152 * g + 0.0722 * b
  const Z = 0.0193 * r + 0.1192 * g + 0.9505 * b
  const sum = X + Y + Z
  if (sum <= 1e-6) return 6500
  const x = X / sum
  const y = Y / sum
  const n = (x - 0.332) / (0.1858 - y)
  return 449 * n ** 3 + 3525 * n ** 2 + 6823.3 * n + 5520.33
}

function inZone(zone: Zone, fx: number, fy: number): boolean {
  switch (zone) {
    case 'left': return fx < 0.25
    case 'right': return fx >= 0.75
    case 'top': return fy < 0.3
    case 'bottom': return fy >= 0.7
    case 'centre': return fx >= 0.25 && fx < 0.75 && fy >= 0.25 && fy < 0.75
    case 'edges': return fx < 0.18 || fx >= 0.82 || fy < 0.18 || fy >= 0.82
    default: return true
  }
}

/** Rows and columns of black bars at the frame's borders, at most 30% per side. */
function trimBars(data: Uint8ClampedArray, w: number, h: number) {
  const dark = (i: number) => data[i] < 22 && data[i + 1] < 22 && data[i + 2] < 22
  const rowDark = (y: number) => { for (let x = 0; x < w; x++) if (!dark((y * w + x) * 4)) return false; return true }
  const colDark = (x: number) => { for (let y = 0; y < h; y++) if (!dark((y * w + x) * 4)) return false; return true }
  let top = 0, bottom = h, left = 0, right = w
  while (top < h * 0.3 && rowDark(top)) top++
  while (bottom > h * 0.7 && rowDark(bottom - 1)) bottom--
  while (left < w * 0.3 && colDark(left)) left++
  while (right > w * 0.7 && colDark(right - 1)) right--
  return { top, bottom, left, right }
}

const BINS = 24

export function analyse(data: Uint8ClampedArray, w: number, h: number, cfg: AmbientConfig): Analysis {
  const { top, bottom, left, right } = trimBars(data, w, h)
  const binW = new Float64Array(BINS)
  const binR = new Float64Array(BINS), binG = new Float64Array(BINS), binB = new Float64Array(BINS)
  let neutralW = 0, nR = 0, nG = 0, nB = 0
  let lumSum = 0, count = 0

  for (let y = top; y < bottom; y++) {
    for (let x = left; x < right; x++) {
      if (!inZone(cfg.zone, (x - left) / (right - left), (y - top) / (bottom - top))) continue
      const i = (y * w + x) * 4
      const r = LINEAR[data[i]], g = LINEAR[data[i + 1]], b = LINEAR[data[i + 2]]
      const Y = 0.2126 * r + 0.7152 * g + 0.0722 * b
      lumSum += Y
      count++
      const [hue, s, v] = hsv(data[i] / 255, data[i + 1] / 255, data[i + 2] / 255)
      if (v < 0.08) continue // too dark to say anything about colour
      const presence = 0.25 + 0.75 * Math.sqrt(Y) // brighter areas dominate what the eye reads
      if (isNeutral(hue, s)) {
        const wgt = presence * (cfg.style === 'mood' ? 0.3 : 1)
        neutralW += wgt; nR += r * wgt; nG += g * wgt; nB += b * wgt
      } else {
        const wgt = presence * (cfg.style === 'mood' ? 0.3 + 2 * s * s : 1)
        const bin = Math.floor(hue / (360 / BINS)) % BINS
        binW[bin] += wgt; binR[bin] += r * wgt; binG[bin] += g * wgt; binB[bin] += b * wgt
      }
    }
  }

  const meanY = count ? lumSum / count : 0
  const luminance = meanY > 0.008856 ? 1.16 * Math.cbrt(meanY) - 0.16 : 9.033 * meanY

  let best = -1, bestW = 0
  for (let k = 0; k < BINS; k++) {
    const wsum = binW[(k + BINS - 1) % BINS] + binW[k] + binW[(k + 1) % BINS]
    if (wsum > bestW) { bestW = wsum; best = k }
  }
  const chromaTotal = binW.reduce((a, b) => a + b, 0)
  const total = chromaTotal + neutralW
  const chromaShare = total > 0 ? bestW / total : 0

  const palette = [...binW.keys()]
    .filter((k) => binW[k] > 0)
    .map((k) => ({ hex: hex(binR[k] / binW[k], binG[k] / binW[k], binB[k] / binW[k]), share: binW[k] / total }))
  if (neutralW > 0) palette.push({ hex: hex(nR / neutralW, nG / neutralW, nB / neutralW), share: neutralW / total })
  palette.sort((a, b) => b.share - a.share)

  let colour: [number, number, number] | null = null
  if (best >= 0) {
    const ks = [(best + BINS - 1) % BINS, best, (best + 1) % BINS]
    const wsum = ks.reduce((a, k) => a + binW[k], 0)
    colour = [ks.reduce((a, k) => a + binR[k], 0) / wsum, ks.reduce((a, k) => a + binG[k], 0) / wsum, ks.reduce((a, k) => a + binB[k], 0) / wsum]
  }
  const [ch, cs] = colour ? hsv(toSrgb(colour[0]), toSrgb(colour[1]), toSrgb(colour[2])) : [0, 0]

  const neutralWins = cfg.whites && (colour === null || chromaShare < (cfg.style === 'mood' ? 0.05 : 0.4) || cs < 0.18)
  const neutral: [number, number, number] = neutralW > 0 ? [nR / neutralW, nG / neutralW, nB / neutralW] : [1, 1, 1]
  const kelvin = Math.max(1800, Math.min(10000, Math.round((kelvinOf(...neutral) + cfg.warmth) / 50) * 50))

  return {
    mode: neutralWins ? 'cct' : 'hsi',
    hue: ch,
    sat: Math.min(100, cs * 100 * (cfg.style === 'mood' ? 1.15 : 1)),
    kelvin,
    luminance: Math.max(0, Math.min(1, luminance)),
    palette: palette.slice(0, 6),
    chromaShare,
  }
}

export interface TrackerConfig { smooth: number; low: number; high: number }
export interface AmbientFrame { mode: 'cct' | 'hsi'; hue: number; sat: number; kelvin: number; brightness: number }

const lerp = (a: number, b: number, k: number) => a + (b - a) * k
const lerpHue = (a: number, b: number, k: number) => (a + ((((b - a) % 360) + 540) % 360 - 180) * k + 360) % 360

/**
 * Smooths analyses into light frames: glides within a shot, snaps on a cut,
 * and only switches between white and colour once the scene has settled on it,
 * so a borderline frame cannot make the light flicker between the two.
 */
export class AmbientTracker {
  private out: AmbientFrame | null = null
  private last: Analysis | null = null
  private pending: { mode: 'cct' | 'hsi'; frames: number } | null = null

  update(a: Analysis, cfg: TrackerConfig): AmbientFrame {
    const level = cfg.low + (cfg.high - cfg.low) * a.luminance
    const target: AmbientFrame = { mode: a.mode, hue: a.hue, sat: a.sat, kelvin: a.kelvin, brightness: level }
    const prev = this.last
    this.last = a
    if (!this.out || !prev) {
      this.out = target
      return { ...target }
    }

    const hueJump = a.mode === 'hsi' && prev.mode === 'hsi' && a.sat > 35 && prev.sat > 35
      && Math.abs((((a.hue - prev.hue) % 360) + 540) % 360 - 180) > 50
    const cut = hueJump || Math.abs(a.luminance - prev.luminance) > 0.25

    let mode = this.out.mode
    if (a.mode !== mode) {
      if (cut) {
        mode = a.mode
        this.pending = null
      } else {
        this.pending = this.pending?.mode === a.mode ? { mode: a.mode, frames: this.pending.frames + 1 } : { mode: a.mode, frames: 1 }
        if (this.pending.frames >= 3) { mode = a.mode; this.pending = null }
      }
    } else {
      this.pending = null
    }

    if (mode !== this.out.mode) {
      this.out = { ...target, mode } // a settled change of kind: no blend between white and colour
      return { ...this.out }
    }
    const k = cut ? 1 : 1 - cfg.smooth * 0.85
    this.out = {
      mode,
      hue: mode === 'hsi' && a.mode === 'hsi' ? lerpHue(this.out.hue, a.hue, k) : this.out.hue,
      sat: mode === 'hsi' && a.mode === 'hsi' ? lerp(this.out.sat, a.sat, k) : this.out.sat,
      kelvin: mode === 'cct' && a.mode === 'cct' ? lerp(this.out.kelvin, a.kelvin, k) : this.out.kelvin,
      brightness: lerp(this.out.brightness, level, k),
    }
    return { ...this.out }
  }
}
