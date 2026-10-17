// @vitest-environment happy-dom
import { beforeEach, expect, it, vi } from 'vitest'
import type { LightView } from '../lib/types'

// The store opens a WebSocket on import; give it one that goes nowhere.
class SilentSocket {
  static OPEN = 1
  readyState = 0
  onopen = null
  onmessage = null
  onclose = null
  send() {}
  close() {}
}
vi.stubGlobal('WebSocket', SilentSocket)

const { useStudio } = await import('../state/store')
const { allOff } = await import('./looks')

const request = vi.fn()
const toast = vi.fn()

beforeEach(() => {
  request.mockReset()
  toast.mockReset()
  useStudio.setState({
    request: request as never, toast,
    lights: [{ id: 'a1', name: 'Backlight' }, { id: 'b2', name: 'Hair light' }] as LightView[],
  })
})

it('All off names the lights that could not be reached and stayed on', async () => {
  request.mockResolvedValue({ type: 'ack', of: 'all.off', skipped: ['a1', 'b2'] })
  await allOff()
  expect(request).toHaveBeenCalledWith({ type: 'all.off' })
  expect(toast).toHaveBeenCalledWith('Backlight, Hair light could not be reached and are still on.', 'error')
})

it('All off says nothing when every light went off', async () => {
  request.mockResolvedValue({ type: 'ack', of: 'all.off', skipped: [] })
  await allOff()
  expect(toast).not.toHaveBeenCalled()
})
