/**
 * SPEC-014 acceptance test: a cue of three looks, built in the window's editor, is stepped through with
 * Go in Glass, Go on the desk and the Space key, on the rendered page against the real service in --demo.
 * Run at 375 px and 1280 px; long names must not widen the page.
 */
import { expect, test, type Page } from '@playwright/test'

const base = () => process.env.GAFFER_URL!

interface ApiLight { id: string; name: string; state: { brightness: number }; engine: { kind: string | null; duration?: number } }

async function key(page: Page): Promise<ApiLight> {
  const all = (await (await page.request.get(`${base()}/api/lights`)).json()).lights as ApiLight[]
  return all.find((l) => l.name === 'Key light')!
}

/** Delete every cue and look, over the page's own socket, so other test files start from a clean store. */
async function reset(page: Page) {
  await page.goto(`${base()}/`)
  await page.evaluate(async () => {
    const ws = new WebSocket(`ws://${location.host}/ws`)
    const hello = await new Promise<{ store: { cues?: { id: string }[]; looks?: { id: string }[] } }>((open) => {
      ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.type === 'hello') open(m) }
    })
    for (const c of hello.store.cues ?? []) ws.send(JSON.stringify({ type: 'cues.delete', id: c.id }))
    for (const l of hello.store.looks ?? []) ws.send(JSON.stringify({ type: 'looks.delete', id: l.id }))
    await new Promise((done) => setTimeout(done, 400))
    ws.close()
  })
}

test.afterEach(async ({ page }) => { await reset(page) })

/** Start from no cues or looks, then save three looks that set the Key light to 21, 32 and 43. */
async function threeLooks(page: Page) {
  await reset(page)
  const light = await key(page)
  for (const [name, brightness] of [['Wide', 21], ['M'.repeat(80), 32], ['Warm', 43]] as const) {
    const saved = await page.request.post(`${base()}/api/looks`, { data: { name, fade_seconds: 0, lights: { [light.id]: { power: true, brightness } } } })
    expect(saved.ok()).toBe(true)
  }
  return light.id
}

const brightness = async (page: Page) => (await key(page)).state.brightness
const widthIsViewport = (page: Page, width: number) =>
  page.evaluate(() => document.documentElement.scrollWidth).then((w) => expect(w).toBe(width))

test('Go steps a cue through its looks in Glass, on the desk and with Space, and a step fade overrides the look', async ({ page }) => {
  await threeLooks(page)

  // Build the cue in the window's editor: three steps, the first with a 30 s fade of its own.
  await page.setViewportSize({ width: 1280, height: 1000 })
  await page.goto(`${base()}/?surface=window`)
  await page.getByLabel('Name of a new cue').fill('C'.repeat(80))
  const pick = page.getByLabel('Look to add to a new cue')
  for (const index of [0, 1, 2]) {
    await pick.selectOption({ index })
    await page.getByRole('button', { name: 'Add step' }).click()
  }
  await page.getByLabel('Fade of step 1 of a new cue in seconds').fill('30')
  await page.getByRole('button', { name: 'Save as cue' }).click()
  await expect(page.getByLabel('Name of cue 1')).toHaveValue('C'.repeat(80))
  await expect(page.getByLabel('Fade of step 1 of cue 1 in seconds')).toHaveValue('30')
  await expect(page.getByLabel('Fade of step 2 of cue 1 in seconds')).toHaveValue('')
  await widthIsViewport(page, 1280)
  await page.screenshot({ path: 'test-results/shots/cues-window.png', fullPage: true })

  // No Go button until a cue is running; Start in the editor readies it at the top and applies nothing.
  await expect(page.getByRole('button', { name: /^Go/ })).toHaveCount(0)
  await page.getByRole('button', { name: 'Start', exact: true }).click()
  await expect(page.getByRole('button', { name: /^Go/ })).toBeVisible()
  await widthIsViewport(page, 1280)

  // Phone width: Go in Glass applies look 1 over the step's 30 s, not the look's 0 s.
  await page.setViewportSize({ width: 375, height: 900 })
  await page.goto(`${base()}/`)
  await page.getByRole('button', { name: 'One light' }).click()
  await expect(page.getByText('Step 0 of 3')).toBeVisible()
  await page.getByRole('button', { name: /^Go Wide/ }).click()
  await expect.poll(async () => (await key(page)).engine).toMatchObject({ kind: 'transition', duration: 30 })
  await expect(page.getByText('Step 1 of 3')).toBeVisible()
  await widthIsViewport(page, 375)
  await page.screenshot({ path: 'test-results/shots/cues-glass.png', fullPage: true })

  // Go on the desk applies look 2 (no step fade, look fade 0: set at once).
  await page.getByRole('button', { name: 'All lights' }).click()
  await page.getByRole('button', { name: /^Go M+/ }).click()
  await expect.poll(() => brightness(page)).toBe(32)
  expect((await key(page)).engine.kind).toBeNull()
  await widthIsViewport(page, 375)
  await page.screenshot({ path: 'test-results/shots/cues-desk.png', fullPage: true })

  // The in-page shortcut (Space, with no control focused) applies look 3.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.keyboard.press('Space')
  await expect.poll(() => brightness(page)).toBe(43)
  await expect(page.getByText('Finished')).toBeVisible()
  await expect(page.getByRole('button', { name: /^Go/ })).toHaveCount(0)

  // Back goes to look 2; Start again returns to the top.
  await page.getByRole('button', { name: 'Back' }).click()
  await expect.poll(() => brightness(page)).toBe(32)
  await expect(page.getByText('Step 2 of 3')).toBeVisible()
})
