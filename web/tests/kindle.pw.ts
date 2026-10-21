/**
 * The Kindle remote (GET /kindle), rendered, against the real service in --demo.
 *
 * The Kindle is a phone to the service: a second browser, no cookie, reaching the service by its
 * Tailscale name, made to come from a non-loopback address by phone_service_main.py (see phone.pw.ts).
 * Its viewport is a Paperwhite 4's screen (1072 x 1448) at the launcher's scale of 2.
 */
import { expect, test, type Browser, type BrowserContext } from '@playwright/test'
import { startPhoneService, TAILNET_NAME, type PhoneService } from './phone-service.ts'

test.use({ launchOptions: { args: [`--host-resolver-rules=MAP ${TAILNET_NAME} 127.0.0.1`] }, storageState: { cookies: [], origins: [] } })

let service: PhoneService
test.beforeAll(async () => { service = await startPhoneService() })
test.afterAll(async () => { await service?.stop() })

const KINDLE = { width: 536, height: 724 }
const mac = () => `http://127.0.0.1:${service.port}`
const remote = () => `http://${TAILNET_NAME}:${service.port}/kindle`

async function macWindow(browser: Browser): Promise<BrowserContext> {
  return browser.newContext({
    storageState: { cookies: [{ name: 'gaffer_session', value: service.secret, domain: '127.0.0.1', path: '/', expires: -1, httpOnly: true, secure: false, sameSite: 'Strict' }], origins: [] },
  })
}

async function switchOn(window: BrowserContext): Promise<string> {
  await window.request.post(`${mac()}/api/phone`, { data: { enabled: false } })
  const reply = await window.request.post(`${mac()}/api/phone`, { data: { enabled: true } })
  expect(reply.status()).toBe(200)
  // The Tailscale name joins the allowed hosts when the (fake) tool answers: wait for it.
  expect((await (await window.request.get(`${mac()}/api/phone?wait=1`)).json()).checking).toBe(false)
  return (await reply.json()).pin as string
}

async function firstLight(window: BrowserContext) {
  const lights = (await (await window.request.get(`${mac()}/api/lights`)).json()).lights
  return lights[0] as { id: string; name: string; state: { power: boolean; brightness: number } }
}

async function typePin(page: import('@playwright/test').Page, pin: string) {
  for (const digit of pin) await page.getByRole('button', { name: digit, exact: true }).click()
}

test('the Kindle remote asks for the PIN, then switches and dims a light', async ({ browser }) => {
  const window = await macWindow(browser)
  const pin = await switchOn(window)
  const kindle = await browser.newContext({ viewport: KINDLE })
  const page = await kindle.newPage()

  // Before the PIN: the page loads (status 401, as for the Glass page) and shows only its PIN pad.
  const first = await page.goto(remote())
  expect(first!.status()).toBe(401)
  await expect(page.getByText('Enter the PIN shown on the Mac, under Phone.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'All off' })).toBeHidden()

  await typePin(page, pin)
  await expect(page.getByRole('status')).toHaveText('Connected')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(KINDLE.width)

  const light = await firstLight(window)
  const card = page.locator('.light').filter({ hasText: light.name })
  const power = card.locator('button.power')
  await expect(power).toHaveText(light.state.power ? 'On' : 'Off')

  // Power: the tap reaches the light, and the button follows the service's state.
  await power.click()
  await expect.poll(async () => (await firstLight(window)).state.power).toBe(!light.state.power)
  await expect(power).toHaveText(light.state.power ? 'Off' : 'On')

  // Brightness up one step: the light goes up 5 and comes on.
  const before = (await firstLight(window)).state.brightness
  await card.getByRole('button', { name: 'Brightness up' }).click()
  await expect.poll(async () => (await firstLight(window)).state.brightness).toBe(Math.min(100, Math.round(before) + 5))
  await expect(card.locator('.val').first()).toContainText(`${Math.min(100, Math.round(before) + 5)}%`)

  // All off reaches every light.
  await page.getByRole('button', { name: 'All off' }).click()
  await expect.poll(async () => {
    const all = (await (await window.request.get(`${mac()}/api/lights`)).json()).lights as { state: { power: boolean } }[]
    return all.every((l) => !l.state.power)
  }).toBe(true)

  await kindle.close()
  await window.close()
})

test('the Kindle remote signs itself back in after it loses its session, and asks again after New PIN', async ({ browser }) => {
  const window = await macWindow(browser)
  const pin = await switchOn(window)
  const kindle = await browser.newContext({ viewport: KINDLE })
  const page = await kindle.newPage()
  await page.goto(remote())
  await typePin(page, pin)
  await expect(page.getByRole('status')).toHaveText('Connected')

  // A Gaffer restart forgets every phone's sign-in. Losing the cookie is the same to the page:
  // it comes back to the studio with no one touching it.
  await kindle.clearCookies()
  await page.reload()
  await expect(page.getByRole('status')).toHaveText('Connected')
  await expect(page.getByText('Enter the PIN shown on the Mac, under Phone.')).toBeHidden()

  // New PIN on the Mac: the open page is signed out, tries its saved PIN once, and asks for the new one.
  await window.request.post(`${mac()}/api/phone/pin`)
  await expect(page.getByText('The PIN changed on the Mac. Enter the new one.')).toBeVisible()
  const status = (await (await window.request.get(`${mac()}/api/phone`)).json()) as { pin: string; locked: boolean }
  expect(status.locked).toBe(false)
  await typePin(page, status.pin)
  await expect(page.getByRole('status')).toHaveText('Connected')

  await kindle.close()
  await window.close()
})

test('after too many wrong PINs the Kindle says so, and Try again asks for the new PIN after New PIN', async ({ browser }) => {
  const window = await macWindow(browser)
  const pin = await switchOn(window)
  const kindle = await browser.newContext({ viewport: KINDLE })
  const page = await kindle.newPage()
  await page.goto(remote())
  await expect(page.getByText('Enter the PIN shown on the Mac, under Phone.')).toBeVisible()

  // Wrong guesses sent from the Kindle page itself (its own origin, as the page would send them) until
  // the service refuses with pin_locked. MAX_WRONG_GUESSES is 100 in service/gaffer/phone.py.
  const wrong = `${pin[0] === '1' ? '2' : '1'}${pin.slice(1)}`
  const replies = await page.evaluate(async (guess) => {
    const out: number[] = []
    for (let i = 0; i < 101; i++) {
      const r = await fetch('/api/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pin: guess }) })
      out.push(r.status)
    }
    return out
  }, wrong)
  expect(replies.slice(0, 99).every((s) => s === 401)).toBe(true)
  expect(replies.slice(99)).toEqual([403, 403])

  // The page's next try is refused as locked: the lock message and a Try again button, visible.
  await typePin(page, wrong)
  await expect(page.getByText('Too many wrong PINs. Press New PIN on the Mac and try again.')).toBeVisible()
  const retry = page.getByRole('button', { name: 'Try again', exact: true })
  await expect(retry).toBeVisible()

  // New PIN on the Mac clears the lock. Try again then asks for the PIN, and the new one signs in.
  await window.request.post(`${mac()}/api/phone/pin`)
  await retry.click()
  await expect(page.getByText('Enter the PIN shown on the Mac, under Phone.')).toBeVisible()
  const status = (await (await window.request.get(`${mac()}/api/phone`)).json()) as { pin: string; locked: boolean }
  expect(status.locked).toBe(false)
  await typePin(page, status.pin)
  await expect(page.getByRole('status')).toHaveText('Connected')

  await kindle.close()
  await window.close()
})
