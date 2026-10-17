/**
 * SPEC-010 acceptance test: keys 1 to 9 apply looks in order and 0 applies All off, on the rendered
 * page, against the real service in --demo. Also the look cards, "More looks" and the window's editor.
 */
import { expect, test, type Page } from '@playwright/test'

const base = () => process.env.GAFFER_URL!

interface ApiLight { id: string; name: string; state: { brightness: number; power: boolean } }

async function lights(page: Page): Promise<ApiLight[]> {
  return (await (await page.request.get(`${base()}/api/lights`)).json()).lights
}

/** Start from no looks, then save four that set the Key light to a different brightness each. */
async function fourLooks(page: Page) {
  const existing = (await (await page.request.get(`${base()}/api/looks`)).json()).looks as { id: string }[]
  await page.goto(`${base()}/`)
  await page.evaluate(async (ids) => {
    const ws = new WebSocket(`ws://${location.host}/ws`)
    await new Promise<void>((open) => { ws.onopen = () => open() })
    for (const id of ids) ws.send(JSON.stringify({ type: 'looks.delete', id }))
    await new Promise((done) => setTimeout(done, 300))
    ws.close()
  }, existing.map((l) => l.id))
  const key = (await lights(page)).find((l) => l.name === 'Key light')!
  for (const [name, brightness] of [['Talking head', 21], ['Product', 32], ['Mood', 43], ['Fourth look', 54]] as const) {
    const saved = await page.request.post(`${base()}/api/looks`, {
      data: { name, fade_seconds: 0, lights: { [key.id]: { power: true, brightness } } },
    })
    expect(saved.ok()).toBe(true)
  }
  return key.id
}

const brightnessOf = async (page: Page, id: string) => (await lights(page)).find((l) => l.id === id)!.state.brightness

test('AC: keys 1 to 9 apply looks in order and 0 turns everything off', async ({ page }) => {
  const key = await fourLooks(page)
  await page.setViewportSize({ width: 390, height: 900 })
  await page.goto(`${base()}/`)
  await expect(page.getByRole('button', { name: 'Talking head' })).toBeVisible()

  await page.keyboard.press('2')
  await expect.poll(() => brightnessOf(page, key)).toBe(32)
  await page.keyboard.press('1')
  await expect.poll(() => brightnessOf(page, key)).toBe(21)
  await page.keyboard.press('4')  // the fourth look is behind "More looks", and the key still reaches it
  await expect.poll(() => brightnessOf(page, key)).toBe(54)
  await page.keyboard.press('9')  // no ninth look: nothing happens
  await page.keyboard.press('0')
  await expect.poll(async () => (await lights(page)).every((l) => !l.state.power)).toBe(true)

  // A digit typed into a text box is text, not a look.
  await page.goto(`${base()}/?surface=window`)
  await page.getByLabel('Name for a new look').fill('3')
  expect((await lights(page)).every((l) => !l.state.power)).toBe(true)
})

test('a fourth look is one tap away under More looks, and the window edits looks', async ({ page }) => {
  const key = await fourLooks(page)
  await page.setViewportSize({ width: 390, height: 900 })
  await page.goto(`${base()}/`)
  await expect(page.getByRole('button', { name: 'Fourth look' })).toHaveCount(0)
  await page.getByRole('button', { name: 'More looks (1)' }).click()
  await page.getByRole('button', { name: 'Fourth look' }).click()
  await expect.poll(() => brightnessOf(page, key)).toBe(54)
  await page.screenshot({ path: 'test-results/shots/looks-phone.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)

  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto(`${base()}/?surface=window`)
  await expect(page.getByLabel('Name of look 4')).toBeVisible()
  await page.screenshot({ path: 'test-results/shots/looks-window.png', fullPage: true })
  const name = page.getByLabel('Name of look 4')
  await name.fill('Renamed')
  await name.blur()
  await expect.poll(async () => (await (await page.request.get(`${base()}/api/looks`)).json()).looks[3].name).toBe('Renamed')
  await page.getByLabel('Delete look 4').click()
  await expect.poll(async () => (await (await page.request.get(`${base()}/api/looks`)).json()).looks.length).toBe(3)
})
