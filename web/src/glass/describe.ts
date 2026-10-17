import { emission, hueName, kelvinName, rgbCss } from '../lib/color'
import type { LightState, LightView } from '../lib/types'

/** The light's colour as CSS, and how strongly it shines (0 when off). */
export function beamOf(state: LightState): { css: string; level: number } {
  const { rgb, level } = emission(state)
  return { css: rgbCss(rgb), level }
}

const pct = (brightness: number) => `${Math.round(brightness)}%`

/** "40% brightness, daylight": the line under the big number. */
export function sentence(state: LightState): string {
  if (!state.power) return 'Off'
  const what = state.mode === 'hsi' ? hueName(state.hsi.hue) : kelvinName(state.cct.kelvin).toLowerCase()
  return `${pct(state.brightness)} brightness, ${what}`
}

/** "SL60IIBi, 4300K, 25%": one line for a light in a list. */
export function summary(light: LightView): string {
  const s = light.state
  if (!s.power) return `${light.model}, off`
  const colour = s.mode === 'hsi' ? hueName(s.hsi.hue) : `${s.cct.kelvin}K`
  return `${light.model}, ${colour}, ${pct(s.brightness)}`
}

/** A model file may name its brand (SPEC-003); lumen's Godox rows do not. */
export function modelLine(light: LightView): string {
  const brand = (light.caps as { brand?: unknown }).brand
  return typeof brand === 'string' && brand ? `${brand} ${light.model}` : light.model
}
