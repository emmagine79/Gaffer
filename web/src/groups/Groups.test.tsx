// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import type { Group } from '../lib/types'
import { useStudio } from '../state/store'
import { Groups } from './Groups'

const light = (id: string) => ({ id, name: id.toUpperCase() })
const group = (id: string, name: string, members: string[]): Group => ({ id, name, members, props: ['brightness'], enabled: true })

async function show(lights: string[], groups: Group[], selected: string | null) {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const send = vi.fn()
  useStudio.setState({ lights: lights.map(light) as never, groups, selected, send })
  const host = document.createElement('div')
  document.body.append(host)
  await act(async () => createRoot(host).render(<Groups />))
  return { host, send }
}

const newGroupButton = (host: HTMLElement) => [...host.querySelectorAll('button')].find((b) => b.textContent === '+ New group')!

afterEach(() => { document.body.replaceChildren() })

it('New group is off unless two lights are in no group, so it never takes a light out of another group', async () => {
  // A and B are grouped, C is free, and A is on screen: the old button was on and would have pulled A out.
  const { host, send } = await show(['a', 'b', 'c'], [group('g1', 'Group 1', ['a', 'b'])], 'a')
  const button = newGroupButton(host)
  expect(button.disabled).toBe(true)
  await act(async () => button.click())
  expect(send).not.toHaveBeenCalled()
  expect(host.textContent).toContain('needs two lights that are in no group')
})

it('New group takes the light on screen and the next free one, and a name no group has', async () => {
  const { host, send } = await show(
    ['a', 'b', 'c', 'd', 'e'],
    [group('g2', 'Group 2', ['a', 'b'])], // Group 1 was deleted: "Group 2" is taken, so the next must not repeat it
    'd',
  )
  await act(async () => newGroupButton(host).click())
  const message = send.mock.calls[0][0] as { group: Group }
  expect(message.group.members).toEqual(['d', 'c'])
  expect(message.group.name).toBe('Group 1')
})

it('a blank group name goes back to the saved name and nothing is sent', async () => {
  const { host, send } = await show(['a', 'b'], [group('g1', 'Pair', ['a', 'b'])], 'a')
  const input = host.querySelector('input.grp-name') as HTMLInputElement
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => { set.call(input, '   '); input.dispatchEvent(new Event('input', { bubbles: true })) })
  await act(async () => { input.dispatchEvent(new FocusEvent('focusout', { bubbles: true })) })
  expect(input.value).toBe('Pair')
  expect(send).not.toHaveBeenCalled()
})
