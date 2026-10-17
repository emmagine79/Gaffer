import { defineConfig } from '@playwright/test'
import { STATE_FILE } from './tests/service.ts'

// Rendered-page tests against the real light service in --demo (plan, architecture call 12).
// Run with `npm run test:e2e`: it builds web/dist first, which the service serves.
export default defineConfig({
  testDir: './tests',
  testMatch: '**/*.pw.ts',
  globalSetup: './tests/service.ts',
  // One service, shared state (renames, scenes): run in order.
  workers: 1,
  fullyParallel: false,
  reporter: 'list',
  use: {
    browserName: 'chromium',
    headless: true,
    storageState: STATE_FILE,
  },
})
