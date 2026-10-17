import { emission, hueName, kelvinName, rgbCss } from '../lib/color'
import type { Caps, LightState, LightView } from '../lib/types'

/** The light's colour as CSS, and how strongly it shines (0 when off). */
export function beamOf(state: LightState): { css: string; level: number } {
  const { rgb, level } = emission(state)
  return { css: rgbCss(rgb), level }
}

const pct = (brightness: number) => `${Math.round(brightness)}%`

/** What the big number and the line under it say about a light's current mode. */
export interface Readout { big: string; unit: string; what: string }

/**
 * Describes the state the light is in: Kelvin for white, degrees for colour, and the mode's
 * own name for gel, effect and RGBW, which have no single Kelvin or hue to show.
 */
export function readout(state: LightState, caps: Pick<Caps, 'effects'>): Readout {
  switch (state.mode) {
    case 'hsi':
      return { big: String(Math.round(state.hsi.hue)), unit: '°', what: hueName(state.hsi.hue) }
    case 'gel':
      return { big: 'Gel', unit: '', what: state.gel ? `gel ${state.gel.label}` : 'gel' }
    case 'fx': {
      const name = caps.effects.find((e) => e.symbol === state.fx?.symbol)?.name
      return { big: 'Effect', unit: '', what: name ?? 'effect' }
    }
    case 'rgbw':
      return { big: 'RGBW', unit: '', what: 'custom colour' }
    default:
      return { big: String(state.cct.kelvin), unit: 'K', what: kelvinName(state.cct.kelvin).toLowerCase() }
  }
}

/** "40% brightness, daylight": the line under the big number. */
export function sentence(state: LightState, caps: Pick<Caps, 'effects'>): string {
  if (!state.power) return 'Off'
  return `${pct(state.brightness)} brightness, ${readout(state, caps).what}`
}

/** "SL60IIBi, 4300K, 25%": one line for a light in a list. */
export function summary(light: LightView): string {
  const s = light.state
  if (!s.power) return `${light.model}, off`
  const { big, unit, what } = readout(s, light.caps)
  return `${light.model}, ${unit === 'K' ? `${big}${unit}` : what}, ${pct(s.brightness)}`
}

/** A model file may name its brand (SPEC-003); lumen's Godox rows do not. */
export function modelLine(light: LightView): string {
  const brand = (light.caps as { brand?: unknown }).brand
  return typeof brand === 'string' && brand ? `${brand} ${light.model}` : light.model
}
