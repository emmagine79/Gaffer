// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import type { Caps, SoftEffect } from '../lib/types'
import { useStudio } from '../state/store'
import { EffectsTab } from './EffectsTab'

const fx = (id: string, name: string): SoftEffect => ({
  id, name, category: 'Nature', description: '', accent: '#ff9a3c', trigger: '', params: [], colour: false, brightness_moves: true,
})

// The Glass chips call lumen's Candle "Flicker". The same running effect must have one name on every screen.
it('the Effects tab names a running Gaffer effect as Glass does, and leaves other effects alone', async () => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  useStudio.setState({
    effects: [fx('candle', 'Candle'), fx('fireplace', 'Fireplace')],
    caps: { effects: [], features: { white: true, colour: true, daylight: false }, min_kelvin: 2700, max_kelvin: 6500 } as unknown as Caps,
    engine: { kind: 'effect', effect: 'candle', label: 'Candle', params: {}, elapsed: 0, duration: null },
    store: null,
  })
  const host = document.createElement('div')
  document.body.append(host)
  await act(async () => createRoot(host).render(<EffectsTab />))
  const tiles = [...host.querySelectorAll('.fx-tile-name')].map((n) => n.textContent)
  expect(tiles).toEqual(['Flicker', 'Fireplace'])
  expect(host.querySelector('.fx-detail')?.textContent).toContain('Flicker')
  expect(host.textContent).not.toContain('Candle')
})
