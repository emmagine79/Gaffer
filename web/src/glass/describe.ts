import { ownLabel } from '../effects/own'
import { emission, hueName, kelvinName, rgbCss } from '../lib/color'
import type { Caps, EngineStatus, LightState, LightView } from '../lib/types'

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
export function readout(state: LightState, caps: Pick<Caps, 'effects' | 'features'>, running?: string | null): Readout {
  // One of Gaffer's own effects is playing: it paints the light, so name it rather than its frames.
  if (running) return { big: 'Effect', unit: '', what: running }
  // Same guard as the panel's controls: a light with no colour has no hue to show.
  const mode = state.mode === 'hsi' && !caps.features.colour ? 'cct' : state.mode
  switch (mode) {
    case 'hsi':
      return { big: String(Math.round(state.hsi.hue)), unit: '°', what: hueName(state.hsi.hue) }
    case 'gel':
      return { big: 'Gel', unit: '', what: state.gel ? `gel ${state.gel.label}` : 'gel' }
    case 'fx': {
      const name = caps.effects.find((e) => e.symbol === state.fx?.symbol)?.name
      return { big: 'Effect', unit: '', what: name ?? (state.fx ? `built-in effect ${state.fx.symbol}` : 'effect') }
    }
    case 'rgbw':
      return { big: 'RGBW', unit: '', what: 'custom colour' }
    default:
      return { big: String(state.cct.kelvin), unit: 'K', what: kelvinName(state.cct.kelvin).toLowerCase() }
  }
}

/** "40% brightness, daylight": the line under the big number. */
export function sentence(state: LightState, caps: Pick<Caps, 'effects' | 'features'>, running?: string | null): string {
  if (!state.power) return 'Off'
  return `${pct(state.brightness)} brightness, ${readout(state, caps, running).what}`
}

/** The name of a Gaffer effect that is playing on this light, if one is. */
export function runningEffect(engine: Pick<EngineStatus, 'kind' | 'effect' | 'label'>): string | null {
  return engine.kind === 'effect' ? ownLabel(engine.effect) ?? (engine.label || 'effect') : null
}

/**
 * What holds a light in gel or effect mode ("Gel L201", "Flicker"), or null in a white or colour mode.
 * The white and colour controls say this instead of the white they would otherwise still show.
 * A playing Gaffer effect (`running`) holds the light too: it streams frames in white or colour mode.
 */
export function heldBy(state: LightState, caps: Pick<Caps, 'effects' | 'features'>, running?: string | null): string | null {
  if (running) return running
  if (state.mode === 'gel') return state.gel ? `Gel ${state.gel.label}` : 'Gel'
  if (state.mode === 'fx') {
    const what = readout(state, caps).what
    return what.charAt(0).toUpperCase() + what.slice(1)
  }
  return null
}

/** "SL60IIBi, 4300K, 25%": one line for a light in a list. */
export function summary(light: LightView): string {
  const s = light.state
  if (!s.power) return `${light.model}, off`
  const { big, unit, what } = readout(s, light.caps, runningEffect(light.engine))
  return `${light.model}, ${unit === 'K' ? `${big}${unit}` : what}, ${pct(s.brightness)}`
}

/** A model file may name its brand (SPEC-003); lumen's Godox rows do not. */
export function modelLine(light: LightView): string {
  const brand = (light.caps as { brand?: unknown }).brand
  return typeof brand === 'string' && brand ? `${brand} ${light.model}` : light.model
}
