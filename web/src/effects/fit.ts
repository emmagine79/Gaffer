import type { Caps, SoftEffect } from '../lib/types'

/** How a software effect plays on this light, when that differs from how it was written. */
export function effectFit(fx: SoftEffect, caps: Caps): string | null {
  if (caps.features.daylight) return fx.brightness_moves ? 'brightness only' : null
  if (!caps.features.colour && fx.colour) return 'as warmth'
  if (!caps.features.white && !fx.colour) return 'as colour'
  return null
}

/** Effects worth offering on this light: on a fixed-daylight light, only those whose brightness moves. */
export function usableEffects(effects: SoftEffect[], caps: Caps | null): SoftEffect[] {
  return caps?.features.daylight ? effects.filter((e) => e.brightness_moves) : effects
}
