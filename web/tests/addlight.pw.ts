/**
 * SPEC-008 acceptance tests: the add-a-light sheet, rendered, against the real service in --demo.
 *
 * The demo scan finds a factory-fresh Godox tube, a Zhiyun and a Yongnuo light (invented adverts).
 * The Zhiyun and Yongnuo stand-ins use the demo driver, which sends nothing.
 */
import { expect, test, type Page } from '@playwright/test'

interface ApiLight { id: string; name: string; model: string; channel: number | null; held: boolean }
interface Ack { type: string; of?: string; light?: string; driver?: string }

const base = () => process.env.GAFFER_URL!

/** Open the page, remembering every identify answer the service sends this page. */
async function open(page: Page, width: number): Promise<Ack[]> {
  const identified: Ack[] = []
  page.on('websocket', (ws) => ws.on('framereceived', (frame) => {
    try {
      const data = JSON.parse(String(frame.payload)) as Ack
      if (data.type === 'ack' && data.of === 'lights.identify') identified.push(data)
    } catch { /* not JSON */ }
  }))
  await page.setViewportSize({ width, height: 900 })
  await page.goto(width >= 1000 ? `${base()}/?surface=window` : `${base()}/`)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  return identified
}

async function lights(page: Page): Promise<ApiLight[]> {
  const res = await page.request.get(`${base()}/api/lights`)
  expect(res.ok()).toBe(true)
  return (await res.json()).lights
}

/** One command over the service's own socket (the same helper glass.pw.ts uses). */
async function command(page: Page, message: Record<string, unknown>) {
  await page.evaluate((m) => new Promise<void>((done, fail) => {
    const ws = new WebSocket(`ws://${location.host}/ws`)
    const timer = setTimeout(() => { ws.close(); fail(new Error('no answer')) }, 5000)
    ws.onmessage = (event) => {
      if (JSON.parse(event.data as string).type === 'hello') {
        ws.send(JSON.stringify(m))
        setTimeout(() => { clearTimeout(timer); ws.close(); done() }, 150)
      }
    }
  }), message)
}

async function openSheet(page: Page) {
  await page.getByRole('button', { name: '+ Add' }).click()
  const sheet = page.getByRole('dialog', { name: 'Add a light' })
  await expect(sheet).toBeVisible()
  await expect(sheet.getByRole('status').first()).toContainText('found nearby', { timeout: 15000 })
  return sheet
}

async function forget(page: Page, name: string) {
  const light = (await lights(page)).find((l) => l.name === name)
  if (light) await command(page, { type: 'lights.forget', light: light.id })
}

async function fitsTheScreen(page: Page) {
  const [scroll, inner] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth])
  expect(scroll).toBe(inner)
}

// AC1: scan lists one light per brand by model name, flashing calls identify() on the right driver,
// and the named light appears in the tabs. Run at phone and desktop width.
for (const width of [375, 1280]) {
  test(`AC1: scan, pick, flash and name a light at ${width}px`, async ({ page }) => {
    const identified = await open(page, width)
    const sheet = await openSheet(page)
    try {
      await expect(sheet.getByRole('button', { name: /TL60/ })).toBeVisible()
      await expect(sheet.getByRole('button', { name: /MOLUS G200 \(demo\)/ })).toBeVisible()
      await expect(sheet.getByRole('button', { name: /YN150Li \(demo\)/ })).toBeVisible()
      await fitsTheScreen(page)

      await sheet.getByRole('button', { name: /MOLUS G200 \(demo\)/ }).click()
      await sheet.getByRole('button', { name: 'Add and flash it' }).click()
      await expect(sheet.getByRole('heading', { name: 'MOLUS G200 (demo) added' })).toBeVisible()
      await expect(sheet.getByText('It flashed. Is this the light you meant?')).toBeVisible()
      const added = (await lights(page)).find((l) => l.model === 'MOLUS G200 (demo)' && l.name === 'MOLUS G200 (demo)')!
      expect(identified).toEqual([expect.objectContaining({ light: added.id, driver: 'demo' })])
      await fitsTheScreen(page)

      await sheet.getByLabel('Name').fill(`Window ${width}`)
      await sheet.getByRole('button', { name: 'Done' }).click()
      await expect(sheet).toBeHidden()
      const tab = page.getByRole('navigation', { name: 'Lights' }).getByRole('button', { name: `Window ${width}`, exact: true })
      await expect(tab).toHaveAttribute('aria-pressed', 'true')
      await expect(page.getByRole('heading', { level: 1 })).toHaveText(`Window ${width}`)
    } finally {
      await forget(page, `Window ${width}`)
      await forget(page, 'MOLUS G200 (demo)')
    }
  })
}

test('AC1: a factory-reset Godox light pairs, flashes and takes a name', async ({ page }) => {
  const identified = await open(page, 1280)
  const sheet = await openSheet(page)
  try {
    await sheet.getByRole('button', { name: /TL60/ }).click()
    await expect(sheet.getByRole('heading', { name: 'TL60 added' })).toBeVisible({ timeout: 20000 })
    await expect(sheet.getByText('It flashed. Is this the light you meant?')).toBeVisible({ timeout: 20000 })
    expect(identified).toEqual([expect.objectContaining({ driver: 'godox' })])
    await sheet.getByLabel('Name').fill('Tube')
    await sheet.getByRole('button', { name: 'Done' }).click()
    await expect(page.getByRole('navigation', { name: 'Lights' }).getByRole('button', { name: 'Tube', exact: true })).toBeVisible()
  } finally {
    await forget(page, 'Tube')
  }
})

// AC2: a demo Yongnuo light cannot be saved without a channel.
test('AC2: a Yongnuo light needs a channel before it is added', async ({ page }) => {
  await open(page, 375)
  const before = (await lights(page)).length
  const sheet = await openSheet(page)
  try {
    await sheet.getByRole('button', { name: /YN150Li \(demo\)/ }).click()
    const add = sheet.getByRole('button', { name: 'Add and flash it' })
    await expect(add).toBeDisabled()
    expect((await lights(page)).length).toBe(before)

    await sheet.getByLabel('Channel').fill('7')
    await expect(add).toBeEnabled()
    await add.click()
    await expect(sheet.getByRole('heading', { name: 'YN150Li (demo) added' })).toBeVisible()
    const saved = (await lights(page)).find((l) => l.model === 'YN150Li (demo)' && l.channel === 7)
    expect(saved).toBeTruthy()
    await sheet.getByRole('button', { name: 'Not this one' }).click() // forgets it and returns to the list
    await expect(sheet.getByRole('button', { name: /YN150Li \(demo\)/ })).toBeVisible({ timeout: 15000 })
    expect((await lights(page)).length).toBe(before)
  } finally {
    await forget(page, 'YN150Li (demo)')
  }
})

// AC3: when a demo driver reports held, the footer names the official app; it clears when held clears.
test('AC3: the footer says which official app holds a light, and stops when it lets go', async ({ page }) => {
  await open(page, 375)
  const panel = (await lights(page)).find((l) => l.name === 'Zhiyun panel')!
  const status = page.locator('.g-status')
  await expect(status).not.toContainText('held')
  await command(page, { type: 'demo.held', light: panel.id, held: true })
  await expect(status).toHaveText('Zhiyun panel is held by the Zhiyun app')
  await command(page, { type: 'demo.held', light: panel.id, held: false })
  await expect(status).not.toContainText('held')
  await expect(status).toContainText('connected')
})

// lumen's sheet clipped its right edge at 360 px: nothing in any step may pass the sheet's edge, and a
// long platform name must not widen it.
test('the sheet fits a 360 px screen in every step, with a very long device name', async ({ page }) => {
  await open(page, 360)
  const sheet = await openSheet(page)
  const insideSheet = async () => sheet.evaluate((el) => {
    const edge = el.getBoundingClientRect()
    const stray = [...el.querySelectorAll('*')].filter((n) => {
      const r = n.getBoundingClientRect()
      return r.width > 0 && (r.right > edge.right + 0.5 || r.left < edge.left - 0.5)
    }).map((n) => `${n.tagName}.${(n as HTMLElement).className}`)
    return { right: edge.right, viewport: window.innerWidth, stray }
  })
  try {
    await sheet.locator('.ad-text small').first().evaluate((el) => { el.textContent = `${'x'.repeat(245)} https://example.test/${'a'.repeat(200)}` })
    let fit = await insideSheet()
    expect(fit.right).toBeLessThanOrEqual(fit.viewport)
    expect(fit.stray).toEqual([])
    await fitsTheScreen(page)

    await sheet.getByRole('button', { name: /YN150Li \(demo\)/ }).click()
    await sheet.getByLabel('Channel').fill('7')
    fit = await insideSheet()
    expect(fit.stray).toEqual([])
    await sheet.getByRole('button', { name: 'Add and flash it' }).click()
    await expect(sheet.getByRole('heading', { name: 'YN150Li (demo) added' })).toBeVisible()
    fit = await insideSheet()
    expect(fit.right).toBeLessThanOrEqual(fit.viewport)
    expect(fit.stray).toEqual([])
    await fitsTheScreen(page)
  } finally {
    await forget(page, 'YN150Li (demo)')
  }
})
