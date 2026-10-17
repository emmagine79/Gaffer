// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { PhonePanel } from './PhonePanel'

const status = (extra: object) => ({ enabled: false, pin: null, locked: false, checking: false, tailscale: null, targets: [], notice: null, ...extra })

async function show(answer: object) {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(answer), { status: 200 })))
  const host = document.createElement('div')
  document.body.append(host)
  await act(async () => createRoot(host).render(<PhonePanel />))
  return host
}

afterEach(() => { document.body.replaceChildren(); vi.unstubAllGlobals() })

it('the panel says when phone access could not be switched back on at start', async () => {
  const message = 'Phone access was on when Gaffer last closed, but it could not be switched back on. Turn it on again to get a new PIN.'
  const host = await show(status({ notice: { code: 'restore_failed', message } }))
  const alert = [...host.querySelectorAll('[role="alert"]')].find((a) => a.textContent === message)
  expect(alert).toBeDefined()
  expect(host.textContent).toContain('Turn on phone access') // still offered, so the owner can turn it on again
})

it('the panel says when a change could not be saved, while phone access is on', async () => {
  const message = 'Gaffer could not save this change.'
  const host = await show(status({ enabled: true, pin: '042917', notice: { code: 'not_saved', message } }))
  expect([...host.querySelectorAll('[role="alert"]')].some((a) => a.textContent === message)).toBe(true)
  expect(host.textContent).toContain('042917')
})
