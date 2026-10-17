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

const TRIO = ['Key light', 'Fill', 'Hair light']
const trioLevels = async (page: Page) => Promise.all(TRIO.map((name) => levelOf(page, name)))

/** Put the three lights at these levels through the service, then open the desk with all three picked. */
async function pickTrio(page: Page, levels: number[], surface: Surface = 'window') {
  await open(page, surface)
  const ids = Object.fromEntries((await lights(page)).map((l) => [l.name, l.id]))
  for (const [i, name] of TRIO.entries()) {
    await command(page, { type: 'set', light: ids[name], patch: { brightness: levels[i] }, fade: 0 })
    await expect.poll(() => levelOf(page, name)).toBe(levels[i])
  }
  await page.getByRole('button', { name: 'All lights' }).click()
  for (const name of TRIO) await strip(page, name).click({ modifiers: ['Shift'], position: { x: 6, y: 6 } })
  await expect(desk(page).locator('.d-strip.picked')).toHaveCount(3)
}

/** The y position on the Key light fader that reads this level (0 at the bottom, 100 at the top). */
async function faderY(page: Page, level: number) {
  const box = (await fader(page, 'Key light').boundingBox())!
  return { x: box.x + box.width / 2, y: box.y + box.height * (1 - level / 100), bottom: box.y + box.height }
}

// Finding 6 (code review): the balance built before a drag must survive dragging the anchor to 0 and back.
test('dragging the first fader to 0 and back to 40 gives 40, 25, 60 again', async ({ page }) => {
  await pickTrio(page, [40, 25, 60])
  const at40 = await faderY(page, 40)
  await page.mouse.move(at40.x, at40.y)
  await page.mouse.down()
  await page.mouse.move(at40.x, at40.bottom + 20, { steps: 20 })
  await expect.poll(() => trioLevels(page)).toEqual([0, 0, 0])
  await page.mouse.move(at40.x, at40.y, { steps: 20 })
  await page.mouse.up()
  await expect.poll(async () => (await trioLevels(page)).map((n) => Math.round(n * 100) / 100)).toEqual([40, 25, 60])
})

// Finding 1: a move that equals the stale value on screen was dropped, so the lights stopped one step short.
test('dragging up and straight back while the service is slow to answer still ends where the finger is', async ({ page }) => {
  let slow = false
  const held: (() => void)[] = []
  await page.routeWebSocket(/\/ws/, (ws) => {
    const server = ws.connectToServer()
    server.onMessage((message) => {
      if (slow) held.push(() => ws.send(message))
      else ws.send(message)
    })
  })
  await pickTrio(page, [20, 10, 30])
  const at20 = await faderY(page, 20)
  const at40 = await faderY(page, 40)
  slow = true
  await page.mouse.move(at20.x, at20.y)
  await page.mouse.down()
  await page.mouse.move(at40.x, at40.y, { steps: 15 })
  await page.mouse.move(at20.x, at20.y, { steps: 15 })
  await page.mouse.up()
  await expect.poll(async () => (await trioLevels(page)).map((n) => Math.round(n * 100) / 100)).toEqual([20, 10, 30])
  slow = false
  held.splice(0).forEach((release) => release())
  await expect(fader(page, 'Key light')).toHaveAttribute('aria-valuenow', '20')
})

// Round 2, finding 3: grabbing a fader again before the service has answered must start from where the lights now are.
test('a second drag started at once, with the service silent, keeps the balance', async ({ page }) => {
  let slow = false
  const held: (() => void)[] = []
  await page.routeWebSocket(/\/ws/, (ws) => {
    const server = ws.connectToServer()
    server.onMessage((message) => {
      if (slow) held.push(() => ws.send(message))
      else ws.send(message)
    })
  })
  await pickTrio(page, [20, 10, 30])
  const at20 = await faderY(page, 20)
  const at40 = await faderY(page, 40)
  slow = true
  await page.mouse.move(at20.x, at20.y)
  await page.mouse.down()
  await page.mouse.move(at40.x, at40.y, { steps: 10 })
  await page.mouse.up()
  await page.mouse.move(at40.x, at40.y)
  await page.mouse.down()
  await page.mouse.move(at20.x, at20.y, { steps: 10 })
  await page.mouse.up()
  await expect.poll(async () => (await trioLevels(page)).map((n) => Math.round(n * 100) / 100)).toEqual([20, 10, 30])
  slow = false
  held.splice(0).forEach((release) => release())
})

// Round 2, finding 4: the last move of a drag is not lost when the desk goes away before its frame runs.
test('leaving the desk in the middle of a drag still sends the last move', async ({ page }) => {
  await pickTrio(page, [20, 10, 30])
  const at20 = await faderY(page, 20)
  const at40 = await faderY(page, 40)
  await page.evaluate(() => { window.requestAnimationFrame = () => 1 }) // no frame ever runs
  await page.mouse.move(at20.x, at20.y)
  await page.mouse.down()
  await page.mouse.move(at40.x, at40.y, { steps: 5 })
  // A click from code, so no pointer event ends the drag first.
  await page.evaluate(() => (document.querySelector('.g-switch button') as HTMLElement).click())
  await expect(desk(page)).toHaveCount(0)
  await expect.poll(async () => (await trioLevels(page)).map((n) => Math.round(n * 100) / 100)).toEqual([40, 20, 60])
  await page.mouse.up()
})

// Round 2, finding 6: after the mouse has used a slider, Tab flips the view, as it does from the bare page.
test('Tab flips the view after the mouse has used a fader', async ({ page }) => {
  await open(page, 'window')
  await page.getByRole('button', { name: 'All lights' }).click()
  const at = await faderY(page, 50)
  await page.mouse.click(at.x, at.y)
  await page.keyboard.press('Tab')
  await expect(desk(page)).toHaveCount(0)
})

// Finding 3: Tab on a control moves focus; it only flips the view from the page itself.
test('Tab on a fader moves focus to the next control and leaves the view alone', async ({ page }) => {
  await open(page, 'window')
  await page.getByRole('button', { name: 'All lights' }).click()
  await fader(page, 'Key light').focus()
  await page.keyboard.press('Tab')
  await expect(desk(page)).toBeVisible()
  await expect(page.getByRole('switch', { name: 'Key light power' })).toBeFocused()
})

// Finding 7: a held finger drifts a few pixels; that must not cancel the long press.
test.describe('on a touch screen', () => {
  test.use({ hasTouch: true })
  test('a long press that drifts 3 px still picks the light', async ({ page }) => {
    await open(page, 'phone', 375)
    await page.getByRole('button', { name: 'All lights' }).click()
    const box = (await strip(page, 'Fill').locator('.d-chip').boundingBox())!
    const point = { x: box.x + box.width / 2, y: box.y + box.height / 2 }
    const cdp = await page.context().newCDPSession(page)
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [point] })
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: point.x + 3, y: point.y + 1 }] })
    await expect(strip(page, 'Fill')).toHaveClass(/picked/)
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
  })
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

test('All off turns into All on, and pressing it again turns every light back on', async ({ page }) => {
  // Captain, 18 Oct 2026: after All off, each light had to be switched on by hand.
  await open(page, 'window')
  await page.getByRole('button', { name: 'All lights' }).click()
  const powers = async () => (await page.request.get(`${base()}/api/lights`).then((r) => r.json())).lights.map((l: { state: { power: boolean } }) => l.state.power)
  await desk(page).getByRole('button', { name: /All off/ }).click()
  await expect.poll(powers).not.toContain(true)
  await desk(page).getByRole('button', { name: /All on/ }).click()
  await expect.poll(powers).not.toContain(false)
  await expect(desk(page).getByRole('button', { name: /All off/ })).toBeVisible()
})

test('the 0 key does what the All off / All on button says', async ({ page }) => {
  await open(page, 'phone', 390)
  const powers = async () => (await page.request.get(`${base()}/api/lights`).then((r) => r.json())).lights.map((l: { state: { power: boolean } }) => l.state.power)
  await page.keyboard.press('0')
  await expect.poll(powers).not.toContain(true)
  await expect(page.getByRole('button', { name: /All on/ })).toBeVisible()  // the page has heard every light go off
  await page.keyboard.press('0')
  await expect.poll(powers).not.toContain(false)
})
