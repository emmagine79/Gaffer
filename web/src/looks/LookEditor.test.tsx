// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, expect, it, vi } from 'vitest'
import type { Look, StoreSnapshot } from '../lib/types'

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
const { LookEditor } = await import('./LookEditor')

const night: Look = { id: 'night', name: 'Night', fade_seconds: 2, lights: {}, updated: 1 } as Look
const withLooks = (looks: Look[]) => ({ settings: { default_fade: 0.6 }, looks }) as unknown as StoreSnapshot

const request = vi.fn(async (_message: Record<string, unknown>) => ({ type: 'ack' }))
const toast = vi.fn()

beforeEach(() => {
  request.mockClear()
  toast.mockClear()
  useStudio.setState({ store: withLooks([night]), request: request as never, toast })
  document.body.replaceChildren()
})

async function show() {
  const host = document.createElement('div')
  document.body.append(host)
  await act(async () => createRoot(host).render(<LookEditor />))
  return host
}

/** Type into a controlled box the way a person does: set the value, then fire the input event. */
async function type(input: HTMLInputElement, text: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => { set.call(input, text); input.dispatchEvent(new Event('input', { bubbles: true })) })
}

it('a save that arrives while the fade box is being typed in keeps the box, its focus and its text', async () => {
  const host = await show()
  const fade = host.querySelector('input[type=number]') as HTMLInputElement
  await act(async () => fade.focus())
  await type(fade, '3.5')
  // The name box was just saved (or another window saved this look): the store hands over the look with a new `updated`.
  await act(async () => useStudio.setState({ store: withLooks([{ ...night, name: 'Renamed', updated: 2 } as Look]) }))
  expect(fade.isConnected).toBe(true)
  expect(document.activeElement).toBe(fade)
  expect(fade.value).toBe('3.5')
  expect((host.querySelector('input[aria-label="Name of look 1"]') as HTMLInputElement).value).toBe('Renamed')
})

it('a fade box that is cleared is not saved as a fade of 0', async () => {
  const host = await show()
  const fade = host.querySelector('input[type=number]') as HTMLInputElement
  await act(async () => fade.focus())
  await type(fade, '')
  await act(async () => fade.blur())
  expect(request).not.toHaveBeenCalled()
  expect(fade.value).toBe('2')
  expect(toast).toHaveBeenCalledWith(expect.stringMatching(/number of seconds/), 'error')
})

it('a new look with an empty fade box leaves the fade to the service default', async () => {
  const host = await show()
  const [, newFade] = host.querySelectorAll<HTMLInputElement>('input[type=number]')
  await type(host.querySelector('input[aria-label="Name for a new look"]') as HTMLInputElement, 'Mood')
  await type(newFade, '')
  await act(async () => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  expect(request).toHaveBeenCalledWith({ type: 'looks.save', look: { name: 'Mood' } })
})
