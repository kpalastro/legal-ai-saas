import { expect, test } from "@playwright/test";

/**
 * Real-stack journey: GoTrue signup/login → intake form → case created and opened.
 * Requires the dev stack (GoTrue :9999, API :8000, web :3000) and is opt-in:
 *
 *   E2E_FULL_STACK=1 npm run test:e2e -- e2e/full-stack.spec.ts
 */
test.skip(
  !process.env.E2E_FULL_STACK,
  "set E2E_FULL_STACK=1 with the local GoTrue/API/web stack running"
);

test("signup, intake and matter open", async ({ page }) => {
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;

  await page.goto("/");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("correct-horse-battery-staple");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: /Sign in/ }).click();

  await expect(page.getByRole("heading", { name: "Your matters" })).toBeVisible({
    timeout: 20_000,
  });

  await page.getByRole("button", { name: "New case" }).click();
  await page.getByLabel("Title").fill("E2E smoke matter");
  await page.getByLabel("Facts").fill("A written contract was breached.");
  await page.getByRole("button", { name: "Create matter" }).click();

  await expect(
    page.getByRole("heading", { name: "E2E smoke matter" })
  ).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("A written contract was breached.")).toBeVisible();
});
