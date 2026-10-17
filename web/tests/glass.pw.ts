/**
 * SPEC-006 acceptance tests: the Glass panel, rendered, against the real service in --demo.
 *
 * The demo seeds Godox lights from lumen's model rows (Key light, Fill, Backlight, Hair light)
 * and one Zhiyun and one Yongnuo stand-in (SPEC-003).
 */
import { expect, test, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'

type Surface = 'menubar' | 'window' | 'phone'
interface ApiLight {
  id: string
  name: string
  state: { brightness: number; power: boolean; mode: string }
  caps: { effects: { symbol: number; name: string }[] }
}

const base = () => process.env.GAFFER_URL!
const SHOTS = process.env.GLASS_SHOTS ?? join(process.cwd(), 'test-results', 'shots')

async function open(page: Page, surface: Surface, width: number, colorScheme: 'light' | 'dark' = 'dark') {
  await page.setViewportSize({ width, height: 900 })
  await page.emulateMedia({ colorScheme })
  await page.goto(surface === 'phone' ? `${base()}/` : `${base()}/?surface=${surface}`)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
}

async function lights(page: Page): Promise<ApiLight[]> {
  const res = await page.request.get(`${base()}/api/lights`)
  expect(res.ok()).toBe(true)
  return (await res.json()).lights
}

/**
 * Send one command over the service's own socket. With `answer`, wait for its reply;
 * commands such as `set` send none, so the caller checks GET /api/lights instead.
 */
async function command(page: Page, message: Record<string, unknown>, answer = true) {
  return page.evaluate(([m, wait]) => new Promise((done, fail) => {
    const ws = new WebSocket(`ws://${location.host}/ws`)
    const timer = setTimeout(() => { ws.close(); fail(new Error('no answer')) }, 5000)
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data as string)
      if (data.type === 'hello') {
        ws.send(JSON.stringify({ ...m, rid: 1 }))
        if (!wait) { clearTimeout(timer); ws.close(); done(null) }
      } else if (data.rid === 1) {
        clearTimeout(timer)
        ws.close()
        if (data.type === 'error') fail(new Error(data.text))
        else done(data)
      }
    }
  }), [message, answer] as const)
}

async function selectLight(page: Page, name: string) {
  const tab = page.getByRole('navigation', { name: 'Lights' }).getByRole('button', { name, exact: true })
  await tab.click()
  await expect(tab).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(name)
}

async function noSideScroll(page: Page) {
  const [scroll, inner] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth])
  expect(scroll).toBe(inner)
}

// AC1 (SPEC AC1): tests/models/godox/ holds a CCT-only and an HSI model file, which the
// harness drops into the service's data folder (<data>/models/, SPEC-003's loader).
// A demo light is moved onto each model through the service's own lights.model command.
for (const [surface, width] of [['phone', 390], ['window', 1280]] as const) {
  test(`AC1: a model file decides the controls at ${width}px`, async ({ page }) => {
    await open(page, surface, width)
    const id = (await lights(page)).find((l) => l.name === 'Backlight')!.id

    await command(page, { type: 'lights.model', light: id, radio_id: 'GLASS-CCT' }, false)
    await selectLight(page, 'Backlight')
    await expect(page.getByText('Example Glass CCT test')).toBeVisible()
    await expect(page.getByRole('slider', { name: 'Brightness' })).toBeVisible()
    await expect(page.getByRole('slider', { name: 'Colour temperature' })).toBeVisible()
    await expect(page.locator('[data-control="colour"]')).toHaveCount(0)
    await expect(page.getByRole('slider', { name: 'Hue' })).toHaveCount(0)

    await command(page, { type: 'lights.model', light: id, radio_id: 'GLASS-HSI' }, false)
    await expect(page.getByText('Example Glass HSI test')).toBeVisible()
    await expect(page.getByRole('slider', { name: 'Hue' })).toBeVisible()
  })
}

test('AC2: dragging brightness changes GET /api/lights for that light', async ({ page }) => {
  await open(page, 'menubar', 360)
  await selectLight(page, 'Hair light')
  const id = (await lights(page)).find((l) => l.name === 'Hair light')!.id
  const before = (await lights(page)).find((l) => l.id === id)!.state.brightness

  const slider = page.getByRole('slider', { name: 'Brightness' })
  const box = (await slider.boundingBox())!
  const y = box.y + box.height / 2
  await page.mouse.move(box.x + box.width * 0.2, y)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * 0.9, y, { steps: 12 })
  await page.mouse.up()

  const shown = Number(await slider.getAttribute('aria-valuenow'))
  expect(shown).not.toBe(before)
  await expect.poll(async () => (await lights(page)).find((l) => l.id === id)!.state.brightness).toBe(shown)
})

// Verifier finding 1: a look can leave a light in gel or effect mode. The big number and the
// line under it must say so, not keep showing the old Kelvin figure.
test('a light in gel or effect mode says so instead of showing a stale Kelvin number', async ({ page }) => {
  await open(page, 'window', 1280)
  await selectLight(page, 'Key light')
  const key = (await lights(page)).find((l) => l.name === 'Key light')!
  const hero = page.locator('.g-hero')
  const line = page.locator('.g-sub')

  const gel = { version: 1, brand: 0, number: 201, sub_brand: 0, label: 'L201', hex: '#3d7bd6' }
  await command(page, { type: 'set', light: key.id, patch: { power: true, brightness: 40, mode: 'gel', gel }, fade: 0 }, false)
  await expect.poll(async () => (await lights(page)).find((l) => l.id === key.id)!.state.mode).toBe('gel')
  await expect(hero).toHaveText('Gel')
  await expect(line).toHaveText('40% brightness, gel L201')

  const effect = key.caps.effects[0]
  await command(page, { type: 'set', light: key.id, patch: { mode: 'fx', fx: { symbol: effect.symbol, speed: null, params: {} } }, fade: 0 }, false)
  await expect.poll(async () => (await lights(page)).find((l) => l.id === key.id)!.state.mode).toBe('fx')
  await expect(hero).toHaveText('Effect')
  await expect(line).toHaveText(`40% brightness, ${effect.name}`)
})

// Verifier finding 5: the Add a light sheet's inputs must show a keyboard focus ring.
test('the Add a light sheet shows a focus ring on its input', async ({ page }) => {
  await open(page, 'window', 1280)
  await page.getByRole('button', { name: '+ Add' }).click()
  const input = page.locator('.ad-sheet input.ad-input').first()
  await input.focus()
  await expect(input).toBeFocused()
  const ring = await input.evaluate((el) => {
    const css = getComputedStyle(el)
    return { style: css.outlineStyle, width: css.outlineWidth, focusVisible: el.matches(':focus-visible') }
  })
  expect(ring.focusVisible).toBe(true)
  expect(ring.style).not.toBe('none')
  expect(ring.width).not.toBe('0px')
})

test('AC3: the panel renders light and dark at 360, 390 and window width', async ({ page }) => {
  // Make the demo look like the mockups: three saved looks, and the lights at their levels.
  await page.goto(`${base()}/?surface=window`)
  const ids = Object.fromEntries((await lights(page)).map((l) => [l.name, l.id]))
  for (const name of ['Talking head', 'Product', 'Moody']) {
    await command(page, { type: 'store.upsert', collection: 'scenes', item: { name }, light: ids['Key light'] })
  }
  const levels: [string, number, number][] = [['Key light', 40, 5600], ['Fill', 25, 4300], ['Hair light', 60, 3200]]
  for (const [name, brightness, kelvin] of levels) {
    await command(page, { type: 'set', light: ids[name], patch: { brightness, mode: 'cct', cct: { kelvin } }, fade: 0 }, false)
    await expect.poll(async () => (await lights(page)).find((l) => l.id === ids[name])!.state.brightness).toBe(brightness)
  }

  mkdirSync(SHOTS, { recursive: true })
  for (const scheme of ['light', 'dark'] as const) {
    for (const [surface, width] of [['menubar', 360], ['phone', 390], ['window', 1280]] as const) {
      const errors: string[] = []
      page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
      page.on('pageerror', (e) => errors.push(e.message))
      await open(page, surface, width, scheme)
      await selectLight(page, 'Key light')
      await expect(page.getByRole('status').first()).toHaveText(/lights connected/)
      await expect(page.getByRole('button', { name: 'Talking head' })).toBeVisible()
      await noSideScroll(page)
      await page.screenshot({ path: join(SHOTS, `glass-${width}-${scheme}.png`), fullPage: true })
      expect(errors).toEqual([])
      page.removeAllListeners('console')
      page.removeAllListeners('pageerror')
    }
  }
})

test('AC4: Open Gaffer posts to the Swift shell in the menu bar and is hidden on phones', async ({ page }) => {
  await page.addInitScript(() => {
    const posted: unknown[] = []
    Object.assign(window, { posted, webkit: { messageHandlers: { gaffer: { postMessage: (m: unknown) => posted.push(m) } } } })
  })
  await open(page, 'menubar', 360)
  await page.getByRole('button', { name: 'Open Gaffer' }).click()
  expect(await page.evaluate(() => (window as unknown as { posted: unknown[] }).posted)).toEqual([{ type: 'open-window' }])

  await open(page, 'phone', 390)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Open Gaffer' })).toHaveCount(0)
})

// Builder checklist 14 and 16: a light's name comes from a Bluetooth advert. The service
// caps a rename at 60 characters, so the socket's answers are rewritten to carry 245.
test('checklist 14, 16: a 245-character name with markup stays text and never widens the page', async ({ page }) => {
  const name = `<img src=x onerror="window.pwned=1">${'W'.repeat(120)} https://example.com/${'a'.repeat(60)}`.padEnd(245, 'z')
  expect(name).toHaveLength(245)
  await page.routeWebSocket(/\/ws/, (ws) => {
    const server = ws.connectToServer()
    server.onMessage((message) => {
      const data = JSON.parse(String(message))
      for (const light of data.lights ?? []) if (light.name === 'Backlight') light.name = name
      ws.send(JSON.stringify(data))
    })
  })
  for (const [surface, width] of [['menubar', 360], ['phone', 390], ['window', 1280]] as const) {
    await open(page, surface, width)
    await page.getByRole('navigation', { name: 'Lights' }).getByRole('button', { name }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(name)
    await noSideScroll(page)
    expect(await page.evaluate(() => 'pwned' in window)).toBe(false)
    await expect(page.locator('img')).toHaveCount(0)
  }
})
