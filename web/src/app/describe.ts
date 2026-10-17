import { hueName, kelvinName } from '../lib/color'
import type { Caps, EngineStatus, LightState, SoftEffect } from '../lib/types'

/** A two-line plain-language description of what the light is doing. */
export function describe(
  s: LightState, engine: EngineStatus, caps: Caps | null, effects: SoftEffect[],
): { title: string; detail: string } {
  if (!s.power) return { title: 'Off', detail: 'The light is switched off' }
  if (engine.kind === 'effect') {
    const fx = effects.find((e) => e.id === engine.effect)
    return { title: engine.label, detail: fx ? `${fx.category} effect, rendered live` : 'Rendered live' }
  }
  if (engine.kind === 'timeline') return { title: engine.label, detail: 'Timeline playing' }
  if (engine.kind === 'stream') return { title: engine.label === 'audio' ? 'Following music' : 'Following the screen', detail: 'Live sync' }
  if (engine.kind === 'transition') return { title: 'Fading', detail: engine.label }
  switch (s.mode) {
    case 'cct': {
      const tint = s.cct.gm === 0 ? 'no tint' : `tint ${s.cct.gm > 0 ? '+' : ''}${s.cct.gm}`
      return { title: kelvinName(s.cct.kelvin), detail: `${s.cct.kelvin} K, ${tint}` }
    }
    case 'hsi': {
      const name = hueName(s.hsi.hue)
      return { title: name[0].toUpperCase() + name.slice(1), detail: `Hue ${Math.round(s.hsi.hue)}°, saturation ${Math.round(s.hsi.sat)}%` }
    }
    case 'rgbw':
      return { title: 'Channel mix', detail: `R ${s.rgbw.r}  G ${s.rgbw.g}  B ${s.rgbw.b}  W ${s.rgbw.w}` }
    case 'gel':
      return { title: s.gel?.label ?? 'Gel', detail: 'Gel emulation' }
    case 'fx': {
      const fx = caps?.effects.find((e) => e.symbol === s.fx?.symbol)
      return { title: fx?.name ?? 'Effect', detail: 'Built into the light' }
    }
  }
}
