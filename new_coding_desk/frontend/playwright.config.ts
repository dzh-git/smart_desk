// ─── Playwright Configuration ───────────────────────────────────────────────
// SmartDesk Speech E2E Test — frontend-backend speech stream consistency.
//
// Requirements
//   - Frontend dev server (Vite) is auto-started by Playwright.
//   - Backend server must be running independently at http://localhost:8000.
//     (Typically via `cd .. && python -m uvicorn backend.main:app --port 8000`)
//   - Test file: e2e/speech-consistency.spec.ts
//   - ONLY Chromium is needed for speech E2E.
//
// Usage
//   npx playwright test --config=playwright.config.ts
//   npm run e2e:speech

import { defineConfig, devices } from "@playwright/test";

const externalBaseURL = process.env.SMARTDESK_PRESENTATION_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  testIgnore: /screen-stream-live\.spec\.ts/,
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: [
    ["list"],
    ["json", { outputFile: "../working/speech-e2e-playwright-report.json" }],
  ],
  use: {
    baseURL: externalBaseURL ?? "http://localhost:5173",
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: externalBaseURL ? undefined : {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 30000,
    cwd: ".",
  },
});
