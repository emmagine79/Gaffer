// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { GodoxImport } from './GodoxImport'

it('the import window shows the steps with the Finder path', async () => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  document.body.append(host)
  await act(async () => createRoot(host).render(<GodoxImport onDone={() => {}} />))
  const steps = [...host.querySelectorAll('.godox-steps li')].map((li) => li.textContent ?? '')
  expect(steps.length).toBeGreaterThanOrEqual(3)
  expect(steps.join(' ')).toMatch(/Finder.*Files tab.*Godox app folder.*GodoxLight\.db/s)
  expect(host.textContent).toContain('Choose GodoxLight.db')
})
