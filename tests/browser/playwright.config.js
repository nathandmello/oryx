const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: ".",
  testMatch: "*.spec.js",
  timeout: 40_000,
  workers: 2,
  forbidOnly: !!process.env.CI,
  use: {
    browserName: "chromium",
    launchOptions: { executablePath: process.env.PM_HUB_CHROMIUM || undefined },
    trace: "retain-on-failure",
  },
});
