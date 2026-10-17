// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import type { Group } from '../lib/types'
import { useStudio } from '../state/store'
import { Groups, planNewGroup } from './Groups'

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

it('New group is off, with a reason, unless two lights are in no group', async () => {
  // A and B are grouped, C is free, and A is on screen.
  const { host } = await show(['a', 'b', 'c'], [group('g1', 'Group 1', ['a', 'b'])], 'a')
  expect(newGroupButton(host).disabled).toBe(true)
  expect(host.textContent).toContain('needs two lights that are in no group')
})

it('a new group is never planned with a light that is already in a group', () => {
  const lights = ['a', 'b', 'c', 'd'].map(light)
  const grouped = [group('g1', 'Group 1', ['a', 'b'])]
  // Only C is free: planning with A on screen must not fall back to A, and must not make a group of one.
  expect(planNewGroup(lights.slice(0, 3), grouped, 'a')).toBeNull()
  expect(planNewGroup(lights.slice(0, 3), grouped, null)).toBeNull()
  // C and D are free: the on-screen free light leads, a grouped on-screen light is ignored.
  expect(planNewGroup(lights, grouped, 'd')?.members).toEqual(['d', 'c'])
  expect(planNewGroup(lights, grouped, 'a')?.members).toEqual(['c', 'd'])
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

it('two quick clicks on the share chips both count', async () => {
  // The service has not answered yet, so the screen still shows the group as it was.
  const { host, send } = await show(['a', 'b'], [{ ...group('g1', 'Pair', ['a', 'b']), props: ['brightness'] }], 'a')
  const chip = (label: string) => [...host.querySelectorAll('[data-part=props] button')].find((b) => b.textContent === label) as HTMLButtonElement
  await act(async () => { chip('White').click(); chip('Colour').click() })
  const last = send.mock.calls.at(-1)![0] as { group: Group }
  expect(send).toHaveBeenCalledTimes(2)
  expect(last.group.props).toEqual(expect.arrayContaining(['brightness', 'white', 'colour']))
  expect(last.group.props).toHaveLength(3)
})
