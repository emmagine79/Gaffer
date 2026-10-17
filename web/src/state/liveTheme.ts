import { emission, luminance, type RGB } from '../lib/color'
import type { LightState } from '../lib/types'
import { useStudio } from './store'

/**
 * Writes the light's live colour into CSS variables on <html>.
 *
 * Runs outside React: during a 30 fps effect the backdrop, rim lights, studio
 * sets and light renders all follow the light without re-rendering a single
 * component. The variables are registered with @property, so the browser
 * interpolates between updates.
 */
let last = ''

function paint(state: LightState | null) {
  if (!state) return
  const { rgb, level } = emission(state)
  const key = `${rgb.map((c) => Math.round(c * 255)).join(',')}|${level.toFixed(3)}`
  if (key === last) return
  last = key
  const root = document.documentElement.style
  root.setProperty('--lr', String(Math.round(rgb[0] * 255)))
  root.setProperty('--lg', String(Math.round(rgb[1] * 255)))
  root.setProperty('--lb', String(Math.round(rgb[2] * 255)))
  root.setProperty('--ll', level.toFixed(3))
  // Headings sit straight on the backdrop, which can swing from a dark room to
  // bright lit paper: estimate the backdrop behind them and pick the ink.
  const paper: RGB = [rgb[0] * 0.902, rgb[1] * 0.89, rgb[2] * 0.863]
  const alpha = level * 0.7
  const backdrop = luminance([0.169, 0.173, 0.188]) * (1 - alpha) + luminance(paper) * alpha
  root.setProperty('--room-ink', backdrop > 0.28 ? '#17181b' : '#ecedef')
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', state.power ? `rgb(${rgb.map((c) => Math.round(c * 60 + 20)).join(' ')})` : '#1e1f23')
}

export function startLiveTheme() {
  paint(useStudio.getState().state)
  return useStudio.subscribe((s, prev) => {
    if (s.state !== prev.state) paint(s.state)
  })
}
