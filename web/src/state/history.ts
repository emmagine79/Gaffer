import { create } from 'zustand'
import type { LightState } from '../lib/types'
import { useStudio } from './store'

/**
 * The last few looks that actually settled, as a one-click undo.
 *
 * A look is recorded only after it has held for SETTLE_MS without the engine
 * running, so dragging a slider through a hundred values makes one entry.
 */
const SETTLE_MS = 1200
const KEEP = 10

const key = (s: LightState) =>
  `${s.power}|${Math.round(s.brightness)}|${s.mode}|${s.cct.kelvin}|${s.cct.gm}|${Math.round(s.hsi.hue)}|${Math.round(s.hsi.sat)}|${s.gel?.label ?? ''}|${s.fx?.symbol ?? ''}|${s.rgbw.r},${s.rgbw.g},${s.rgbw.b},${s.rgbw.w}`

export const useHistory = create<{ looks: LightState[] }>()(() => ({ looks: [] }))

let timer = 0

export function startHistory() {
  return useStudio.subscribe((s, prev) => {
    if (s.state === prev.state || !s.state || s.engine.kind) return
    window.clearTimeout(timer)
    const candidate = s.state
    timer = window.setTimeout(() => {
      const now = useStudio.getState()
      if (now.state !== candidate || now.engine.kind || !candidate.power) return
      const k = key(candidate)
      useHistory.setState(({ looks }) => ({
        looks: [candidate, ...looks.filter((l) => key(l) !== k)].slice(0, KEEP),
      }))
    }, SETTLE_MS)
  })
}
