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
const { ScheduleEditor } = await import('./ScheduleEditor')

const look = (id: string, name: string) => ({ id, name, fade_seconds: 1, lights: {}, updated: 1 }) as Look
const withLooks = (looks: Look[]) => ({ settings: { default_fade: 0.6 }, looks, schedules: [] }) as unknown as StoreSnapshot

const request = vi.fn(async (_message: Record<string, unknown>) => ({ type: 'ack' }))

beforeEach(() => {
  request.mockClear()
  useStudio.setState({ store: withLooks([look('night', 'Night'), look('day', 'Day')]), request: request as never, toast: vi.fn() })
  document.body.replaceChildren()
})

async function show() {
  const host = document.createElement('div')
  document.body.append(host)
  await act(async () => createRoot(host).render(<ScheduleEditor />))
  return host
}

/** Change a box the way a person does: set the value, then fire the event React listens for. */
async function enter(element: HTMLInputElement | HTMLSelectElement, value: string) {
  const proto = element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype
  const set = Object.getOwnPropertyDescriptor(proto, 'value')!.set!
  await act(async () => {
    set.call(element, value)
    element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }))
  })
}

const addButton = (host: HTMLElement) => [...host.querySelectorAll('button')].find((b) => b.textContent === 'Add schedule')!

it('a look picked and then deleted is not sent: the schedule uses the look the list now shows', async () => {
  const host = await show()
  await enter(host.querySelector('input[aria-label="Name for a new schedule"]') as HTMLInputElement, 'Evening')
  await enter(host.querySelector('select[aria-label="Look to apply"]') as HTMLSelectElement, 'day')
  await act(async () => useStudio.setState({ store: withLooks([look('night', 'Night')]) }))  // "Day" is deleted
  await act(async () => addButton(host).click())
  expect(request).toHaveBeenCalledOnce()
  expect(request.mock.calls[0][0]).toMatchObject({ type: 'schedules.save', schedule: { action: 'look', target: 'night' } })
})

it('Add schedule is off while the time box is empty', async () => {
  const host = await show()
  await enter(host.querySelector('input[aria-label="Name for a new schedule"]') as HTMLInputElement, 'Evening')
  expect(addButton(host).disabled).toBe(false)
  await enter(host.querySelector('input[aria-label="Time"]') as HTMLInputElement, '')
  expect(addButton(host).disabled).toBe(true)
})
