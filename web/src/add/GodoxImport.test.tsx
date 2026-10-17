// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { useStudio } from '../state/store'
import { GodoxImport, MAX_FILE_BYTES } from './GodoxImport'

async function show(onBack = () => {}) {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  document.body.append(host)
  await act(async () => createRoot(host).render(<GodoxImport onDone={() => {}} onBack={onBack} />))
  return host
}

it('pasting an export shows how many lights were imported and which were skipped', async () => {
  const select = vi.fn()
  const request = vi.fn().mockResolvedValue({
    type: 'ack', light: 'a1', lights: ['a1', 'b2'], skipped: ['Test spare: those keys are not usable'],
  })
  useStudio.setState({ request, select })
  const onDone = vi.fn()
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  document.body.append(host)
  await act(async () => createRoot(host).render(<GodoxImport onDone={onDone} onBack={() => {}} />))
  expect(host.querySelector('.godox-steps')?.textContent).toMatch(/Finder.*Files tab.*GodoxLight\.db/s)

  const box = host.querySelector('textarea') as HTMLTextAreaElement
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set?.call(box, '{"netKeys": []}')
    box.dispatchEvent(new Event('input', { bubbles: true }))
  })
  const importButton = [...host.querySelectorAll('button')].find((b) => /import pasted text/i.test(b.textContent ?? ''))
  await act(async () => importButton?.click())

  expect(request).toHaveBeenCalledWith({ type: 'lights.import', meshJson: '{"netKeys": []}' }, 30000)
  expect(host.querySelector('h2')?.textContent).toMatch(/2 lights imported/)
  expect(host.querySelector('.hint')?.textContent).toContain('Skipped Test spare: those keys are not usable')
  const done = [...host.querySelectorAll('button')].find((b) => /^done$/i.test((b.textContent ?? '').trim()))
  await act(async () => done?.click())
  expect(onDone).toHaveBeenCalledOnce()
})

it('a file too large for the socket gets a plain message and is never sent', async () => {
  const request = vi.fn()
  const toast = vi.fn()
  useStudio.setState({ request, toast })
  const host = await show()
  const input = host.querySelector('input[type=file]') as HTMLInputElement
  Object.defineProperty(input, 'files', { value: [new File([new Uint8Array(MAX_FILE_BYTES + 1)], 'GodoxLight.db')] })
  await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(request).not.toHaveBeenCalled()
  expect(toast).toHaveBeenCalledWith(expect.stringMatching(/too large/i), 'error')
})

it('choosing the same oversize file again runs the check again', async () => {
  const toast = vi.fn()
  useStudio.setState({ request: vi.fn(), toast })
  const host = await show()
  const input = host.querySelector('input[type=file]') as HTMLInputElement
  // Within the file-size limit, but too big once base64 and the message around it are added.
  Object.defineProperty(input, 'files', { value: [new File([new Uint8Array(MAX_FILE_BYTES)], 'GodoxLight.db')] })
  let chosen = 'C:\\fakepath\\GodoxLight.db'
  Object.defineProperty(input, 'value', { get: () => chosen, set: (v: string) => { chosen = v } })
  await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(toast).toHaveBeenCalledTimes(1)
  expect(chosen).toBe('') // a browser fires no change event for the same file unless the input is empty
})

it('the window has a way back to the list of lights', async () => {
  const onBack = vi.fn()
  const host = await show(onBack)
  const back = [...host.querySelectorAll('button')].find((b) => /back/i.test(b.textContent ?? ''))
  await act(async () => back?.click())
  expect(onBack).toHaveBeenCalledOnce()
})
