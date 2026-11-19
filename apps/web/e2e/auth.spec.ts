import { expect, test } from "@playwright/test";

test("auth screen gates on the acknowledgement", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "LexSim AI" })).toBeVisible();
  await page.getByLabel("Email").fill("smoke@example.com");
  await page.getByLabel("Password").fill("correct-horse-battery-staple");
  await page.getByRole("button", { name: /Sign in/ }).click();
  // Next renders its own role="alert" route announcer, so match the message.
  await expect(
    page.getByText(/Please acknowledge the privacy and AI-assistance notice/i)
  ).toBeVisible();
});

test("the privacy/LPP notice can be acknowledged", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Before you continue")).toBeVisible();
  const checkbox = page.getByRole("checkbox");
  await checkbox.check();
  await expect(checkbox).toBeChecked();
});
