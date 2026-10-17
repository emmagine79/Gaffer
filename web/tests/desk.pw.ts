/**
 * SPEC-007 acceptance tests: the lighting desk, the view switch and the Tab key,
 * rendered, against the real service in --demo.
 */
import { expect, test, type Page } from '@playwright/test'

type Surface = 'menubar' | 'window' | 'phone'
interface ApiLight { id: string; name: string; state: { brightness: number } }

const base = () => process.env.GAFFER_URL!
const urlOf = (surface: Surface) => (surface === 'phone' ? `${base()}/` : `${base()}/?surface=${surface}`)

async function lights(page: Page): Promise<ApiLight[]> {
  const res = await page.request.get(`${base()}/api/lights`)
  expect(res.ok()).toBe(true)
  return (await res.json()).lights
}

const levelOf = async (page: Page, name: string) => (await lights(page)).find((l) => l.name === name)!.state.brightness

/** Send one command over the service's own socket; `set` sends no reply, so callers poll /api/lights. */
async function command(page: Page, message: Record<string, unknown>) {
  await page.evaluate((m) => new Promise<void>((done, fail) => {
    const ws = new WebSocket(`ws://${location.host}/ws`)
    const timer = setTimeout(() => { ws.close(); fail(new Error('no answer')) }, 5000)
    ws.onmessage = (event) => {
      if (JSON.parse(event.data as string).type === 'hello') {
        ws.send(JSON.stringify(m))
        clearTimeout(timer)
        setTimeout(() => { ws.close(); done() }, 100)
      }
    }
  }), message)
}

async function open(page: Page, surface: Surface, width = 1280) {
  await page.setViewportSize({ width, height: 900 })
  await page.goto(urlOf(surface))
  await expect(page.getByRole('group', { name: 'View' })).toBeVisible()
  await expect(page.getByRole('status').first()).toHaveText(/lights connected/)
}

const desk = (page: Page) => page.getByRole('region', { name: 'Lighting desk' })
const strip = (page: Page, name: string) => desk(page).locator('.d-strip', { has: page.getByRole('button', { name, exact: true }) })
const fader = (page: Page, name: string) => desk(page).getByRole('slider', { name: `${name} brightness` })

// SPEC AC4
test('AC4: select three lights at 40, 25 and 60, drag the first to 80: the service holds 80, 50, 100', async ({ page }) => {
  await open(page, 'window')
  const ids = Object.fromEntries((await lights(page)).map((l) => [l.name, l.id]))
  const start: [string, number][] = [['Key light', 40], ['Fill', 25], ['Hair light', 60], ['Backlight', 70]]
  for (const [name, brightness] of start) {
    await command(page, { type: 'set', light: ids[name], patch: { brightness }, fade: 0 })
    await expect.poll(() => levelOf(page, name)).toBe(brightness)
  }

  await page.getByRole('button', { name: 'All lights' }).click()
  await expect(desk(page)).toBeVisible()
  for (const name of ['Key light', 'Fill', 'Hair light']) await strip(page, name).click({ modifiers: ['Shift'], position: { x: 6, y: 6 } })
  await expect(desk(page).locator('.d-strip.picked')).toHaveCount(3)

  // Press on the thumb (40%), then move straight up to 80% so no follower is pushed past its limit on the way.
  const box = (await fader(page, 'Key light').boundingBox())!
  const x = box.x + box.width / 2
  await page.mouse.move(x, box.y + box.height * 0.6)
  await page.mouse.down()
  await page.mouse.move(x, box.y + box.height * 0.2, { steps: 20 })
  await page.mouse.up()

  await expect(fader(page, 'Key light')).toHaveAttribute('aria-valuenow', '80')
  await expect.poll(async () => [await levelOf(page, 'Key light'), await levelOf(page, 'Fill'), await levelOf(page, 'Hair light')].map(Math.round))
    .toEqual([80, 50, 100])
  expect(await levelOf(page, 'Backlight')).toBe(70) // not picked, not moved
})

// SPEC AC8
test('AC8: the switch shows the desk, Tab shows Glass again, a reload opens on the last view', async ({ page }) => {
  await open(page, 'phone', 390)
  await page.getByRole('button', { name: 'All lights' }).click()
  await expect(desk(page)).toBeVisible()

  await page.keyboard.press('Tab')
  await expect(desk(page)).toHaveCount(0)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

  await page.keyboard.press('Tab')
  await expect(desk(page)).toBeVisible()
  await page.reload()
  await expect(desk(page)).toBeVisible()

  // Each surface remembers its own view: the Mac window still opens on Glass.
  await open(page, 'window')
  await expect(desk(page)).toHaveCount(0)

  await open(page, 'phone', 390)
  await page.getByRole('button', { name: 'One light' }).click()
  await page.reload()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(desk(page)).toHaveCount(0)
})

test('tapping a strip name opens that light in Glass', async ({ page }) => {
  await open(page, 'menubar', 360)
  await page.getByRole('button', { name: 'All lights' }).click()
  await strip(page, 'Fill').getByRole('button', { name: 'Fill', exact: true }).click()
  await expect(desk(page)).toHaveCount(0)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Fill')
})

// Builder checklist 14 and 16: a light's name comes from a Bluetooth advert. The service caps a
// rename at 60 characters, so the socket's answers are rewritten to carry 245.
test('checklist 14, 16: a 245-character name with markup stays text and never widens the desk', async ({ page }) => {
  const name = `<img src=x onerror="window.pwned=1">${'W'.repeat(120)} https://example.com/${'a'.repeat(60)}`.padEnd(245, 'z')
  await page.routeWebSocket(/\/ws/, (ws) => {
    const server = ws.connectToServer()
    server.onMessage((message) => {
      const data = JSON.parse(String(message))
      for (const light of data.lights ?? []) if (light.name === 'Backlight') light.name = name
      ws.send(JSON.stringify(data))
    })
  })
  for (const [surface, width] of [['menubar', 360], ['phone', 390], ['window', 1280]] as const) {
    await page.goto(urlOf(surface))
    await page.setViewportSize({ width, height: 900 })
    await page.getByRole('button', { name: 'All lights' }).click()
    await expect(strip(page, name)).toBeVisible()
    const [scroll, inner] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth])
    expect(scroll).toBe(inner)
    expect(await page.evaluate(() => 'pwned' in window)).toBe(false)
    await expect(page.locator('img')).toHaveCount(0)
  }
})
