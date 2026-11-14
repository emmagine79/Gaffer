// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
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
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const { useStudio } = await import('../state/store')
const { allOff, useLookKeys } = await import('./looks')

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

function Keys() {
  useLookKeys()
  return null
}

it.each(['addLight', 'connectionSheet', 'palette'] as const)('keys 0 to 9 do nothing while %s is open', async (sheet) => {
  const lights = [{ id: 'a1', name: 'Backlight', state: { power: true } }] as LightView[]
  useStudio.setState({ [sheet]: true, lights, store: { looks: [{ id: 'night' }] } as never })
  const root = createRoot(document.createElement('div'))
  await act(async () => root.render(createElement(Keys)))
  for (const key of ['0', '1']) window.dispatchEvent(new KeyboardEvent('keydown', { key, cancelable: true }))
  expect(request).not.toHaveBeenCalled()
  useStudio.setState({ [sheet]: false })
  window.dispatchEvent(new KeyboardEvent('keydown', { key: '0', cancelable: true }))
  expect(request).toHaveBeenCalledWith({ type: 'all.off' })
  await act(async () => root.unmount())
})

it('keys 0 to 9 do nothing while a dialog such as Phone access is open', async () => {
  const lights = [{ id: 'a1', name: 'Backlight', state: { power: true } }] as LightView[]
  useStudio.setState({ lights, store: { looks: [{ id: 'night' }] } as never })
  const dialog = document.body.appendChild(document.createElement('dialog'))
  dialog.setAttribute('open', '')
  const root = createRoot(document.createElement('div'))
  await act(async () => root.render(createElement(Keys)))
  for (const key of ['0', '1']) window.dispatchEvent(new KeyboardEvent('keydown', { key, cancelable: true }))
  expect(request).not.toHaveBeenCalled()
  dialog.removeAttribute('open')
  window.dispatchEvent(new KeyboardEvent('keydown', { key: '0', cancelable: true }))
  expect(request).toHaveBeenCalledWith({ type: 'all.off' })
  await act(async () => root.unmount())
  dialog.remove()
})
