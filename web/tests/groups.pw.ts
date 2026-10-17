/**
 * SPEC-011 acceptance tests: sync groups in the rendered page, against the real service in --demo.
 */
import { expect, test, type Page } from '@playwright/test'

interface ApiLight { id: string; name: string; state: { brightness: number } }

const base = () => process.env.GAFFER_URL!

async function open(page: Page, width: number) {
  await page.setViewportSize({ width, height: 900 })
  // No ?surface= is the phone page; the window is the wide one. Both show Groups.
  await page.goto(width >= 1000 ? `${base()}/?surface=window` : `${base()}/`)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
}

async function lights(page: Page): Promise<ApiLight[]> {
  const res = await page.request.get(`${base()}/api/lights`)
  expect(res.ok()).toBe(true)
  return (await res.json()).lights
}

const levelOf = async (page: Page, name: string) => (await lights(page)).find((l) => l.name === name)!.state.brightness

/** Drag the Brightness slider on screen from one fraction of its width to another. */
async function drag(page: Page, from: number, to: number) {
  const slider = page.getByRole('slider', { name: 'Brightness' })
  const box = (await slider.boundingBox())!
  const y = box.y + box.height / 2
  await page.mouse.move(box.x + box.width * from, y)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * to, y, { steps: 12 })
  await page.mouse.up()
  return Number(await slider.getAttribute('aria-valuenow'))
}

for (const width of [375, 1280]) {
  test(`AC1, AC2: a group of two lights moves together until it is deleted, at ${width}px`, async ({ page }) => {
    await open(page, width)
    const tab = page.getByRole('navigation', { name: 'Lights' }).getByRole('button', { name: 'Key light', exact: true })
    await tab.click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Key light')

    // A new group holds the light on screen and the next light that is in no group.
    await page.getByRole('button', { name: '+ New group' }).click()
    const group = page.locator('.grp')
    await expect(group).toHaveCount(1)
    const members = group.locator('[data-part=members] [aria-pressed=true]')
    await expect(members).toHaveText(['Key light', 'Fill'])
    await expect(group.locator('[data-part=props] [aria-pressed=true]')).toContainText(['Brightness'])

    // AC1: moving Key light in Glass moves Fill.
    const fillBefore = await levelOf(page, 'Fill')
    const moved = await drag(page, 0.2, 0.9)
    await expect.poll(() => levelOf(page, 'Key light')).toBe(moved)
    await expect.poll(() => levelOf(page, 'Fill')).toBe(moved)
    expect(moved).not.toBe(fillBefore)

    // A long name stays inside the page (checklist 16).
    await group.getByLabel('Group name').fill('W'.repeat(40))
    await group.getByLabel('Group name').blur()
    await expect(page.locator('.grp-name')).toHaveValue('W'.repeat(40))
    const [scroll, inner] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth])
    expect(scroll).toBe(inner)

    // AC2: deleting the group stops it.
    await group.getByRole('button', { name: /^Delete / }).click()
    await expect(page.locator('.grp')).toHaveCount(0)
    const next = await drag(page, 0.9, 0.3)
    expect(next).not.toBe(moved)
    await expect.poll(() => levelOf(page, 'Key light')).toBe(next)
    // The mirror runs inside the same command that moves Key light, so Fill has had its chance.
    expect(await levelOf(page, 'Fill')).toBe(moved)
  })
}
