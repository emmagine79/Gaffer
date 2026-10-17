/**
 * SPEC-013 acceptance test: the window's schedule editor saves and lists schedules, at phone and
 * desktop width, against the real service in --demo.
 */
import { expect, test, type Page } from '@playwright/test'

const base = () => process.env.GAFFER_URL!

const stored = async (page: Page) =>
  ((await (await page.request.get(`${base()}/api/export`)).json()).schedules ?? []) as { name: string; at: string; days: number[]; action: string; target?: string; enabled: boolean }[]

for (const width of [375, 1280]) {
  test(`the schedule editor saves and lists schedules at ${width} px`, async ({ page }) => {
    const key = (await (await page.request.get(`${base()}/api/lights`)).json()).lights[0].id
    const moody = (await (await page.request.post(`${base()}/api/looks`, {
      data: { name: `Moody ${width}`, fade_seconds: 0, lights: { [key]: { power: true, brightness: 20 } } },
    })).json()).look.id as string

    await page.setViewportSize({ width, height: 900 })
    await page.goto(`${base()}/?surface=window`)
    const editor = page.getByRole('region', { name: 'Schedules' })
    await expect(editor).toBeVisible()

    // A look at 22:15 on Monday to Friday, with a name that is one long unbroken word.
    const longName = `Evening${'x'.repeat(60)}${width}`
    await editor.getByLabel('Name for a new schedule').fill(longName)
    await editor.getByLabel('Time').fill('22:15')
    await editor.getByLabel('Look to apply').selectOption({ label: `Moody ${width}` })
    await editor.getByRole('button', { name: 'Add schedule' }).click()
    await expect(editor.getByText(longName)).toBeVisible()
    await expect(editor.getByText(`Look: Moody ${width}, Mon Tue Wed Thu Fri`)).toBeVisible()

    // And an everything-off one on Saturday and Sunday.
    await editor.getByLabel('What happens').selectOption('off')
    await editor.getByLabel('Name for a new schedule').fill(`Lights out ${width}`)
    await editor.getByLabel('Time').fill('01:30')
    for (const day of ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']) {  // flips all seven: weekdays off, weekend on
      await editor.getByRole('group', { name: 'Days' }).getByRole('button', { name: day }).click()
    }
    await editor.getByRole('button', { name: 'Add schedule' }).click()
    await expect(editor.getByText(`All off, Sat Sun`)).toBeVisible()

    await expect.poll(async () => (await stored(page)).filter((s) => s.name.endsWith(String(width)))).toEqual([
      { id: expect.any(String), name: longName, enabled: true, at: '22:15', days: [0, 1, 2, 3, 4], action: 'look', target: moody, created: expect.any(Number), updated: expect.any(Number) },
      { id: expect.any(String), name: `Lights out ${width}`, enabled: true, at: '01:30', days: [5, 6], action: 'off', created: expect.any(Number), updated: expect.any(Number) },
    ])

    // The list is still there after a reload, a schedule can be paused and then deleted, and the page never scrolls sideways.
    await page.reload()
    await expect(editor.getByText(longName)).toBeVisible()
    await editor.getByRole('button', { name: `Lights out ${width} on or off` }).click()
    await expect(editor.getByRole('button', { name: `Lights out ${width} on or off` })).toHaveText('Paused')
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width)
    await page.screenshot({ path: `test-results/shots/schedules-${width}.png`, fullPage: true })
    await editor.getByRole('button', { name: `Delete schedule ${longName}` }).click()
    await editor.getByRole('button', { name: `Delete schedule Lights out ${width}` }).click()
    await expect.poll(async () => (await stored(page)).filter((s) => s.name.endsWith(String(width)))).toEqual([])
  })
}
