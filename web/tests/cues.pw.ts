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

  // The in-page shortcut is the Gaffer window's: Space, with no control focused, applies look 3.
  await page.setViewportSize({ width: 1280, height: 1000 })
  await page.goto(`${base()}/?surface=window`)
  await expect(page.getByText('Step 2 of 3')).toBeVisible()
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.keyboard.press('Space')
  await expect.poll(() => brightness(page)).toBe(43)
  await expect(page.getByText('Finished')).toBeVisible()
  await expect(page.getByRole('button', { name: /^Go/ })).toHaveCount(0)

  // Back goes to look 2; Start again returns to the top.
  await page.getByRole('button', { name: 'Back', exact: true }).click()
  await expect.poll(() => brightness(page)).toBe(32)
  await expect(page.getByText('Step 2 of 3')).toBeVisible()
})

/** Over the page's own socket: save a cue of the given look names (in order) and make it the active one. */
async function startCueOf(page: Page, names: string[]) {
  await page.evaluate(async (wanted) => {
    const ws = new WebSocket(`ws://${location.host}/ws`)
    const hello = await new Promise<{ store: { looks: { id: string; name: string }[] } }>((open) => {
      ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.type === 'hello') open(m) }
    })
    const steps = wanted.map((name) => ({ look_id: hello.store.looks.find((l) => l.name === name)!.id, fade_seconds: null }))
    ws.send(JSON.stringify({ type: 'cues.save', cue: { id: 'show', name: 'Show', steps } }))
    await new Promise((done) => setTimeout(done, 300))
    ws.send(JSON.stringify({ type: 'cue.start', id: 'show' }))
    await new Promise((done) => setTimeout(done, 300))
    ws.close()
  }, names)
}

test('Space does not fire Go in the menu-bar panel or behind the Add a light sheet, and Go names the look it will run', async ({ page }) => {
  const lightId = await threeLooks(page)
  // threeLooks gave the middle look an 80 character name; rename the set so the label can be read.
  for (const [name, brightness] of [['Close', 55]] as const) {
    await page.request.post(`${base()}/api/looks`, { data: { name, fade_seconds: 0, lights: { [lightId]: { power: true, brightness } } } })
  }
  await page.goto(`${base()}/`)
  await startCueOf(page, ['Wide', 'Close', 'Warm'])

  // Menu-bar panel: Space does nothing, so the light is not touched.
  await page.setViewportSize({ width: 360, height: 700 })
  await page.goto(`${base()}/?surface=menubar`)
  await expect(page.getByText('Step 0 of 3')).toBeVisible()
  await page.keyboard.press('Space')
  await page.waitForTimeout(400)
  await expect(page.getByText('Step 0 of 3')).toBeVisible()

  // Window with the Add a light sheet open and nothing focused: Space does nothing behind it.
  await page.setViewportSize({ width: 1280, height: 1000 })
  await page.goto(`${base()}/?surface=window`)
  await expect(page.getByText('Step 0 of 3')).toBeVisible()
  await page.getByRole('button', { name: '+ Add' }).click()
  await expect(page.getByRole('dialog', { name: 'Add a light' })).toBeVisible()
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.keyboard.press('Space')
  await page.waitForTimeout(400)
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Add a light' })).toHaveCount(0)
  await expect(page.getByText('Step 0 of 3')).toBeVisible()
  await expect(page.getByRole('button', { name: /^Go Wide/ })).toBeVisible()

  // Go runs Wide. The look of step 2 is then deleted: the button must name Warm, the look Go will really run.
  await page.getByRole('button', { name: /^Go Wide/ }).click()
  await expect(page.getByText('Step 1 of 3')).toBeVisible()
  await page.evaluate(async () => {
    const ws = new WebSocket(`ws://${location.host}/ws`)
    const hello = await new Promise<{ store: { looks: { id: string; name: string }[] } }>((open) => {
      ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.type === 'hello') open(m) }
    })
    ws.send(JSON.stringify({ type: 'looks.delete', id: hello.store.looks.find((l) => l.name === 'Close')!.id }))
    await new Promise((done) => setTimeout(done, 300))
    ws.close()
  })
  await expect(page.getByRole('button', { name: /^Go Warm/ })).toBeVisible()
  await page.getByRole('button', { name: /^Go Warm/ }).click()
  await expect.poll(() => brightness(page)).toBe(43)
})
