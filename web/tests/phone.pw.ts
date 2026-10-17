/**
 * SPEC-015 acceptance tests: phone access, rendered, against the real service in --demo.
 *
 * The Mac window is a loopback browser with the launch secret. The phone is a second browser at
 * 375 px with no cookie that reaches the service by the Tailscale name from a fake `tailscale`
 * tool (Chromium maps that name to this machine). The service sees a connection that names a host
 * other than 127.0.0.1, so it treats it as a phone and asks for the PIN.
 */
import { expect, test, type Page } from '@playwright/test'
import { startPhoneService, TAILNET_NAME, type PhoneService } from './phone-service.ts'

test.use({ launchOptions: { args: [`--host-resolver-rules=MAP ${TAILNET_NAME} 127.0.0.1`] }, storageState: { cookies: [], origins: [] } })

let service: PhoneService
test.beforeAll(async () => { service = await startPhoneService() })
test.afterAll(async () => { await service?.stop() })

const mac = () => `http://127.0.0.1:${service.port}`

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
  const window = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    storageState: { cookies: [{ name: 'gaffer_session', value: service.secret, domain: '127.0.0.1', path: '/', expires: -1, httpOnly: true, secure: false, sameSite: 'Strict' }], origins: [] },
  })
  const macPage = await window.newPage()
  await macPage.goto(`${mac()}/?surface=window`)
  await macPage.getByRole('button', { name: 'Phone' }).click()
  await macPage.getByRole('button', { name: 'Turn on phone access' }).click()
  await expect(macPage.getByLabel('PIN', { exact: true })).toHaveText(/^\d{6}$/)
  const pin = (await macPage.getByLabel('PIN', { exact: true }).textContent())!
  const tailscaleUrl = `http://${TAILNET_NAME}:${service.port}/`
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

  // New PIN on the Mac signs that phone out.
  await macPage.getByRole('button', { name: 'New PIN' }).click()
  await expect(macPage.getByLabel('PIN', { exact: true })).not.toHaveText(pin)
  expect(await page.evaluate(async () => (await fetch('/api/lights')).status)).toBe(401)
  await window.close()
  await phone.close()
})
