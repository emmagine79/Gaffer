/**
 * SPEC-015 acceptance tests: phone access, rendered, against the real service in --demo.
 *
 * The Mac window is a loopback browser with the launch secret. The phone is a second browser at
 * 375 px with no cookie that reaches the service by the Tailscale name from a fake `tailscale`
 * tool (Chromium maps that name to this machine). The service sees a connection that names a host
 * other than 127.0.0.1, so it treats it as a phone and asks for the PIN. A connection from this machine
 * is loopback, which the gate refuses for any such host (SPEC-024), so phone-service.ts starts the service
 * through phone_service_main.py, which gives the phone's requests a non-loopback address.
 */
import { expect, test, type Browser, type Page } from '@playwright/test'
import { startPhoneService, TAILNET_NAME, type PhoneService } from './phone-service.ts'

test.use({ launchOptions: { args: [`--host-resolver-rules=MAP ${TAILNET_NAME} 127.0.0.1`] }, storageState: { cookies: [], origins: [] } })

let service: PhoneService
test.beforeAll(async () => { service = await startPhoneService() })
test.afterAll(async () => { await service?.stop() })

const mac = () => `http://127.0.0.1:${service.port}`

/** A browser context signed in as the Mac window. */
const macWindow = (browser: Browser) => browser.newContext({
  viewport: { width: 1280, height: 800 },
  storageState: { cookies: [{ name: 'gaffer_session', value: service.secret, domain: '127.0.0.1', path: '/', expires: -1, httpOnly: true, secure: false, sameSite: 'Strict' }], origins: [] },
})

// The tests share one service: each starts with phone access off.
test.beforeEach(async ({ browser }) => {
  const window = await macWindow(browser)
  await window.request.post(`${mac()}/api/phone`, { data: { enabled: false } })
  await window.close()
})

/** Read the QR code in an <img> by drawing it on a canvas and giving that to the browser's own barcode reader. */
async function decode(page: Page, alt: string): Promise<string> {
  return page.evaluate(async (label) => {
    const img = document.querySelector<HTMLImageElement>(`img[alt="${label}"]`)!
    await img.decode()
    const canvas = document.createElement('canvas')
    canvas.width = img.naturalWidth
    canvas.height = img.naturalHeight
    canvas.getContext('2d')!.drawImage(img, 0, 0)
    const Detector = (window as unknown as { BarcodeDetector: new (o: object) => { detect: (c: HTMLCanvasElement) => Promise<{ rawValue: string }[]> } }).BarcodeDetector
    return (await new Detector({ formats: ['qr_code'] }).detect(canvas))[0].rawValue
  }, alt)
}

async function noSideways(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(await page.evaluate(() => window.innerWidth))
}

test('the QR codes decode to addresses a phone can reach, and the phone needs the PIN there', async ({ browser }) => {
  // The Mac window switches phone access on and shows the codes and the PIN.
  const window = await macWindow(browser)
  const macPage = await window.newPage()
  await macPage.goto(`${mac()}/?surface=window`)
  await macPage.getByRole('button', { name: 'Phone' }).click()
  await macPage.getByRole('button', { name: 'Turn on phone access' }).click()
  await expect(macPage.getByLabel('PIN', { exact: true })).toHaveText(/^\d{6}$/)
  const pin = (await macPage.getByLabel('PIN', { exact: true }).textContent())!
  const tailscaleUrl = `http://${TAILNET_NAME}:${service.port}/`
  await expect(macPage.locator('.ph-url', { hasText: tailscaleUrl })).toBeVisible() // the service does not wait for the Tailscale tool
  const shown = await macPage.locator('.ph-url').allTextContents()
  expect(shown).toContain(tailscaleUrl)
  for (const label of ['Same Wi-Fi', 'Away, over Tailscale']) {
    if (!(await macPage.locator(`img[alt="QR code for ${label}"]`).count())) continue // a Mac with no Wi-Fi shows only Tailscale
    expect(shown).toContain(await decode(macPage, `QR code for ${label}`))
  }
  expect(await decode(macPage, 'QR code for Away, over Tailscale')).toBe(tailscaleUrl)

  // The phone scans it: the address in the code reaches the PIN screen, not the studio.
  const phone = await browser.newContext({ viewport: { width: 375, height: 812 } })
  const page = await phone.newPage()
  const [first] = await Promise.all([page.waitForResponse(() => true), page.goto(tailscaleUrl)])
  expect(first.status()).toBe(401)
  await expect(page.getByLabel('Enter the PIN shown on the Mac')).toBeVisible()
  await expect(page.getByRole('group', { name: 'View' })).toHaveCount(0)
  await noSideways(page)

  // A wrong PIN is refused in words; the right one opens the studio.
  const wrong = pin === '000000' ? '000001' : '000000'
  await page.getByLabel('Enter the PIN shown on the Mac').fill(wrong)
  await page.getByRole('button', { name: 'Connect' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'not right' })).toBeVisible()
  await noSideways(page)
  await page.getByLabel('Enter the PIN shown on the Mac').fill(pin)
  await page.getByRole('button', { name: 'Connect' }).click()
  await expect(page.getByRole('group', { name: 'View' })).toBeVisible()
  await noSideways(page)

  // A phone that adds ?surface=window is not offered the Mac's Phone button.
  const sneaky = await phone.newPage()
  const [answer] = await Promise.all([sneaky.waitForResponse((r) => new URL(r.url()).pathname === '/api/phone'), sneaky.goto(`${tailscaleUrl}?surface=window`)])
  expect(answer.status()).toBe(403)
  await expect(sneaky.getByRole('group', { name: 'View' })).toBeVisible()
  await expect(sneaky.getByRole('button', { name: 'Phone' })).toHaveCount(0)
  await sneaky.close()

  // New PIN on the Mac signs that phone out, and the open page goes back to the PIN screen.
  await macPage.getByRole('button', { name: 'New PIN' }).click()
  await expect(macPage.getByLabel('PIN', { exact: true })).not.toHaveText(pin)
  expect(await page.evaluate(async () => (await fetch('/api/lights')).status)).toBe(401)
  await expect(page.getByLabel('Enter the PIN shown on the Mac')).toBeVisible()
  await expect(page.getByRole('group', { name: 'View' })).toHaveCount(0)

  await window.close()
  await phone.close()
})

test('the Mac window keeps its Phone button when a request fails, and stops saying "checking" when the wait is dropped', async ({ browser }) => {
  const window = await macWindow(browser)
  const macPage = await window.newPage()
  let first = true
  await macPage.route(/\/api\/phone$/, (route) => { if (first) { first = false; return route.abort() } return route.continue() })
  await macPage.route(/\/api\/phone\?wait=1$/, (route) => route.abort())
  await macPage.goto(`${mac()}/?surface=window`)

  // The first look at phone access failed on the network: the button stays, and opening the panel asks again.
  await macPage.getByRole('button', { name: 'Phone' }).click()
  await macPage.getByRole('button', { name: 'Turn on phone access' }).click()
  await expect(macPage.getByLabel('PIN', { exact: true })).toHaveText(/^\d{6}$/)
  // The held-open request for the Tailscale answer was dropped: the panel does not stay on "checking" for ever.
  await expect(macPage.getByText('Tailscale: checking')).toHaveCount(0)
  await window.close()
})

test('a late "are you signed in?" answer does not send a phone that has just signed in back to the PIN screen', async ({ browser }) => {
  const macCtx = await macWindow(browser)
  const macPage = await macCtx.newPage()
  await macPage.goto(`${mac()}/?surface=window`)
  await macPage.getByRole('button', { name: 'Phone' }).click()
  await macPage.getByRole('button', { name: 'Turn on phone access' }).click()
  const pinOf = async () => (await macPage.getByLabel('PIN', { exact: true }).textContent())!
  await expect(macPage.getByLabel('PIN', { exact: true })).toHaveText(/^\d{6}$/)
  const pin = await pinOf()

  // This phone's page holds back the answer to every "am I signed in?" question once told to.
  const phone = await browser.newContext({ viewport: { width: 375, height: 812 } })
  const page = await phone.newPage()
  await page.addInitScript(() => {
    const w = window as unknown as { __hold: boolean; __held: (() => void)[]; __delivered: number }
    const real = window.fetch.bind(window)
    w.__hold = false; w.__held = []; w.__delivered = 0
    window.fetch = async (input, init) => {
      const res = await real(input, init)
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (w.__hold && (init?.method ?? 'GET') === 'GET' && new URL(url, location.href).pathname === '/api/session') {
        await new Promise<void>((release) => w.__held.push(release))
        w.__delivered++
      }
      return res
    }
  })
  await page.goto(`http://${TAILNET_NAME}:${service.port}/`)
  await page.getByLabel('Enter the PIN shown on the Mac').fill(pin)
  await page.getByRole('button', { name: 'Connect' }).click()
  await expect(page.getByRole('group', { name: 'View' })).toBeVisible()

  // New PIN signs the phone out: it shows the PIN screen. Its socket keeps retrying, and each try asks again; hold those answers.
  await macPage.getByRole('button', { name: 'New PIN' }).click()
  await expect(page.getByLabel('Enter the PIN shown on the Mac')).toBeVisible()
  await page.evaluate(() => { (window as unknown as { __hold: boolean }).__hold = true })
  await expect.poll(() => page.evaluate(() => (window as unknown as { __held: unknown[] }).__held.length)).toBeGreaterThan(0)

  // The phone signs in with the new PIN, and only then do the old answers arrive.
  await expect(macPage.getByLabel('PIN', { exact: true })).not.toHaveText(pin)
  await page.getByLabel('Enter the PIN shown on the Mac').fill(await pinOf())
  await page.getByRole('button', { name: 'Connect' }).click()
  await expect(page.getByRole('group', { name: 'View' })).toBeVisible()
  const late = await page.evaluate(() => { const w = window as unknown as { __held: (() => void)[] }; w.__held.forEach((release) => release()); return w.__held.length })
  await expect.poll(() => page.evaluate(() => (window as unknown as { __delivered: number }).__delivered)).toBeGreaterThanOrEqual(late)
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))))
  await expect(page.getByRole('group', { name: 'View' })).toBeVisible()
  await expect(page.getByLabel('Enter the PIN shown on the Mac')).toHaveCount(0)
  await phone.close()
  await macCtx.close()
})
