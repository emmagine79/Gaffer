/**
 * SPEC-012 acceptance tests: effects in Glass, rendered, against the real service in --demo.
 *
 * The demo seeds Godox lights from lumen's model rows (Key light has built-in effects, Fill is
 * bi-colour, Backlight is fixed daylight) plus a Zhiyun and a Yongnuo stand-in with none.
 */
import { expect, test, type Page } from '@playwright/test'

interface ApiLight {
  id: string
  name: string
  state: { brightness: number; power: boolean; mode: string; cct: { kelvin: number } }
  caps: { effects: { symbol: number; name: string }[]; features: { colour: boolean } }
  engine: { kind: string | null }
}

const base = () => process.env.GAFFER_URL!
const WIDTHS = [375, 1280] as const

async function open(page: Page, width: number) {
  await page.setViewportSize({ width, height: 900 })
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.goto(`${base()}/?surface=${width < 600 ? 'phone' : 'window'}`)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
}

async function lights(page: Page): Promise<ApiLight[]> {
  const res = await page.request.get(`${base()}/api/lights`)
  expect(res.ok()).toBe(true)
  return (await res.json()).lights
}

const lightNamed = async (page: Page, name: string) => (await lights(page)).find((l) => l.name === name)!

/** Send one command over the service's own socket; no reply is awaited (`set` sends none). */
async function command(page: Page, message: Record<string, unknown>) {
  await page.evaluate((m) => new Promise<void>((done, fail) => {
    const ws = new WebSocket(`ws://${location.host}/ws`)
    const timer = setTimeout(() => { ws.close(); fail(new Error('no hello')) }, 5000)
    ws.onmessage = (event) => {
      if (JSON.parse(event.data as string).type === 'hello') {
        ws.send(JSON.stringify(m))
        clearTimeout(timer)
        setTimeout(() => { ws.close(); done() }, 150)
      }
    }
  }), message)
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

const builtin = (page: Page) => page.locator('[data-fx-group="builtin"]')
const own = (page: Page) => page.locator('[data-fx-group="gaffer"]')

for (const width of WIDTHS) {
  // AC1: built-in effects show only when the model file lists them, and match its row.
  test(`AC1: the built-in list matches the model row, and Zhiyun has none, at ${width}px`, async ({ page }) => {
    await open(page, width)
    const key = await lightNamed(page, 'Key light')
    expect(key.caps.effects.length).toBeGreaterThan(0)
    await selectLight(page, 'Key light')
    const names = await builtin(page).getByRole('button').allTextContents()
    expect(names).toEqual(key.caps.effects.map((e) => e.name))

    const fill = await lightNamed(page, 'Fill')
    await selectLight(page, 'Fill')
    expect(await builtin(page).getByRole('button').allTextContents()).toEqual(fill.caps.effects.map((e) => e.name))

    const zhiyun = await lightNamed(page, 'Zhiyun panel')
    expect(zhiyun.caps.effects).toEqual([])
    await selectLight(page, 'Zhiyun panel')
    await expect(page.getByRole('region', { name: 'Effects' })).toBeVisible()
    await expect(builtin(page)).toHaveCount(0)
    await expect(own(page).getByRole('button')).toHaveText(['Breathe', 'Flicker', 'Colour cycle'])
    await noSideScroll(page)
  })

  // AC2: Gaffer's Breathe moves a CCT-only light's brightness through the engine, with the notice.
  test(`AC2: Breathe moves a CCT-only light's brightness, with the notice, at ${width}px`, async ({ page }) => {
    await open(page, width)
    await selectLight(page, 'Yongnuo wand')
    const wand = await lightNamed(page, 'Yongnuo wand')
    expect(wand.caps.features.colour).toBe(false)
    await expect(page.getByRole('note')).toContainText('run from the Mac')
    await expect(page.getByRole('note')).toContainText('stop if the Mac sleeps')
    await expect(page.getByRole('note')).toContainText('stutter over Bluetooth')

    await own(page).getByRole('button', { name: 'Breathe' }).click()
    await expect(own(page).getByRole('button', { name: 'Breathe' })).toHaveAttribute('aria-pressed', 'true')
    const seen = new Set<number>()
    await expect.poll(async () => {
      seen.add(Math.round((await lightNamed(page, 'Yongnuo wand')).state.brightness))
      return seen.size
    }, { timeout: 8000, intervals: [250] }).toBeGreaterThan(3)
    expect((await lightNamed(page, 'Yongnuo wand')).state.mode).toBe('cct')

    await page.getByRole('button', { name: 'Stop effect' }).click()
    await expect(own(page).getByRole('button', { name: 'Breathe' })).toHaveAttribute('aria-pressed', 'false')
    await noSideScroll(page)
  })
}

test('Colour cycle plays as warmth on a CCT-only light', async ({ page }) => {
  await open(page, 1280)
  await selectLight(page, 'Fill')
  await expect(own(page).getByRole('button', { name: /Colour cycle/ })).toContainText('as warmth')
  await own(page).getByRole('button', { name: /Colour cycle/ }).click()
  await expect(own(page).getByRole('button', { name: /Colour cycle/ })).toHaveAttribute('aria-pressed', 'true')
  const kelvins = new Set<number>()
  await expect.poll(async () => {
    kelvins.add((await lightNamed(page, 'Fill')).state.cct.kelvin)
    return kelvins.size
  }, { timeout: 8000, intervals: [250] }).toBeGreaterThan(3)
  await page.getByRole('button', { name: 'Stop effect' }).click()
  await expect(own(page).getByRole('button', { name: /Colour cycle/ })).toHaveAttribute('aria-pressed', 'false')
  await expect(page.getByRole('button', { name: 'Stop effect' })).toHaveCount(0)
})

test('a built-in effect runs on the light, and the hero names it', async ({ page }) => {
  await open(page, 1280)
  await selectLight(page, 'Key light')
  const key = await lightNamed(page, 'Key light')
  const effect = key.caps.effects[1]
  await builtin(page).getByRole('button', { name: effect.name, exact: true }).click()
  await expect.poll(async () => (await lightNamed(page, 'Key light')).state.mode).toBe('fx')
  await expect(page.locator('.g-hero')).toHaveText('Effect')
  await expect(page.locator('.g-sub')).toContainText(effect.name)
})

// SPEC-006 left two gaps. In gel or effect mode the controls below the hero kept showing white.
test('in gel mode the controls stop showing white-mode values', async ({ page }) => {
  await open(page, 1280)
  await selectLight(page, 'Key light')
  const key = await lightNamed(page, 'Key light')
  const gel = { version: 1, brand: 0, number: 201, sub_brand: 0, label: 'L201', hex: '#3d7bd6' }
  await command(page, { type: 'set', light: key.id, patch: { power: true, brightness: 40, mode: 'gel', gel }, fade: 0 })
  await expect(page.locator('.g-hero')).toHaveText('Gel')
  await expect(page.getByRole('slider', { name: 'Colour temperature' })).toHaveCount(0)
  await expect(page.locator('.g-ctl', { hasText: 'Colour temperature' })).toContainText('Not in use')
  await expect(page.locator('[data-control="colour"] .g-lab')).toContainText('Gel L201')
  await expect(page.locator('[data-control="colour"] .g-lab')).not.toContainText('White')

  await page.getByRole('button', { name: 'Back to white' }).click()
  await expect(page.getByRole('slider', { name: 'Colour temperature' })).toBeVisible()
  await expect(page.locator('[data-control="colour"] .g-lab')).toContainText('White')
  await expect.poll(async () => (await lightNamed(page, 'Key light')).state.mode).toBe('cct')
})

// The chip's own name is the one the hero and the sentence use (lumen calls these "Candle" and "Rainbow").
test('a running Gaffer effect is named as its chip names it, and the controls stop showing live frames', async ({ page }) => {
  await open(page, 1280)
  await selectLight(page, 'Yongnuo wand')
  await own(page).getByRole('button', { name: 'Flicker' }).click()
  await expect(page.locator('.g-hero')).toHaveText('Effect')
  await expect(page.locator('.g-sub')).toContainText('Flicker')
  await expect(page.locator('.g-sub')).not.toContainText('Candle')
  await expect(page.getByRole('slider', { name: 'Colour temperature' })).toHaveCount(0)
  await expect(page.locator('.g-ctl', { hasText: 'Colour temperature' })).toContainText('Not in use')
  await page.getByRole('button', { name: 'Stop effect' }).click()
  await expect(page.locator('.g-hero')).not.toHaveText('Effect')
  await expect(page.getByRole('slider', { name: 'Colour temperature' })).toBeVisible()
})

test('Colour cycle on a colour light says so, and the colour controls stop following its frames', async ({ page }) => {
  await open(page, 1280)
  await selectLight(page, 'Key light')
  await own(page).getByRole('button', { name: /Colour cycle/ }).click()
  await expect(own(page).getByRole('button', { name: /Colour cycle/ })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.g-sub')).toContainText('Colour cycle')
  await expect(page.locator('.g-sub')).not.toContainText('Rainbow')
  await expect(page.locator('[data-control="colour"] .g-lab')).toContainText('Not in use')
  await expect(page.getByRole('slider', { name: 'Hue' })).toHaveCount(0)
  await expect(page.getByRole('slider', { name: 'Saturation' })).toHaveCount(0)
  await expect(page.getByRole('slider', { name: 'Colour temperature' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Stop effect' }).click()
  await expect(page.getByRole('slider', { name: 'Hue' })).toBeVisible()
})

test('a built-in effect the model row does not list still gets a name', async ({ page }) => {
  // Rewrite what the socket says about Key light so it always claims an effect its model row does not
  // have: the first hello and every later message that carries that light's state.
  let keyId = ''
  const fake = (state: Record<string, unknown>) => ({ ...state, mode: 'fx', fx: { symbol: 99, speed: null, params: {} } })
  await page.routeWebSocket(/\/ws/, (ws) => {
    const server = ws.connectToServer()
    server.onMessage((message) => {
      const data = JSON.parse(String(message))
      for (const light of data.lights ?? []) {
        if (light.name === 'Key light') { keyId = light.id; light.state = fake(light.state) }
      }
      if (data.type === 'state' && data.light === keyId) data.state = fake(data.state)
      ws.send(JSON.stringify(data))
    })
  })
  await open(page, 1280)
  await selectLight(page, 'Key light')
  await expect(page.locator('.g-hero')).toHaveText('Effect')
  await expect(page.locator('.g-sub')).toContainText('built-in effect 99')
})

// A brightness change sends `set`, which ends a playing Gaffer effect. The panel says so instead of ending it silently.
test('while a Gaffer effect plays, Brightness is not offered, and the effect keeps playing until it is stopped', async ({ page }) => {
  await open(page, 1280)
  await selectLight(page, 'Yongnuo wand')
  const slider = page.getByRole('slider', { name: 'Brightness' })
  await expect(slider).toBeVisible()
  await own(page).getByRole('button', { name: 'Flicker' }).click()
  const control = page.locator('.g-ctl', { hasText: 'Brightness' })
  await expect(control).toContainText('Not in use')
  await expect(slider).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'More brightness' })).toHaveCount(0)
  await page.waitForTimeout(500)
  expect((await lightNamed(page, 'Yongnuo wand')).engine.kind).toBe('effect')
  await control.getByRole('button', { name: 'Stop to adjust' }).click()
  await expect(slider).toBeVisible()
  await expect.poll(async () => (await lightNamed(page, 'Yongnuo wand')).engine.kind).toBeNull()
})
