import { expect, test } from "@playwright/test";

const API = "http://localhost:8000";
const CASE_ID = "11111111-1111-1111-1111-111111111111";

const me = {
  id: "22222222-2222-2222-2222-222222222222",
  email: "mock@example.com",
  role: "individual",
  subscription_tier: null,
  erased_at: null,
  limits: { cases: 2, simulations_per_month: 3 },
  usage: { cases: 1, simulations_this_month: 0 },
};

const caseRow = {
  id: CASE_ID,
  org_id: null,
  title: "Mock contract dispute",
  jurisdiction: "NSW Supreme Court",
  court: "NSW Supreme Court",
  cause_of_action: "contract_breach",
  status: "intake",
  created_at: "2026-11-19T00:00:00Z",
};

const detail = {
  ...caseRow,
  description: "A written contract was breached.",
  parties: [{ name: "A. Plaintiff", role: "plaintiff" }],
  issues: ["Was there a breach?"],
  relief_sought: "Damages",
  case_number: "2026/1",
  legal_hold: false,
  erased_at: null,
  simulation_count: 0,
  document_count: 0,
  generated_document_count: 0,
  deadline_count: 0,
};

test("authenticated workspace lists and opens a matter", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("lexsim_token", "test-access-token");
    localStorage.setItem("lexsim_refresh", "test-refresh-token");
  });

  await page.route(`${API}/**`, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (body: unknown) => route.fulfill({ json: body as object });

    if (path === "/users/me") return json(me);
    if (path === "/cases") return json([caseRow]);
    if (path === "/organisations") return json([]);
    if (path === "/billing/plans") return json([]);
    if (path === "/legal/resources") return json({ resources: [], disclaimer: "" });
    if (path === "/legal/court-policies") {
      return json({
        court: "NSW Supreme Court",
        policy: "Practice Note SC Gen 23",
        ai_disclosure_required: true,
        citation_verification_required: true,
        human_review_required: true,
        prohibited_doc_types: [],
        notes: "Verify the current practice note.",
        disclaimer: "Not legal advice.",
      });
    }
    if (path === "/legal/elements") {
      return json({ cause: "contract", known: true, elements: ["Offer"], disclaimer: "" });
    }
    if (path === `/cases/${CASE_ID}`) return json(detail);
    if (
      path.endsWith("/simulations") ||
      path.endsWith("/documents") ||
      path.endsWith("/generated-documents") ||
      path.endsWith("/deadlines")
    ) {
      return json([]);
    }
    return route.fulfill({ status: 404, json: { detail: `no mock for ${path}` } });
  });

  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Your matters" })).toBeVisible();
  await expect(page.getByText(caseRow.title)).toBeVisible();
  await page.getByRole("button", { name: new RegExp(caseRow.title) }).click();

  await expect(page.getByRole("heading", { name: caseRow.title })).toBeVisible();
  await expect(page.getByText("A written contract was breached.")).toBeVisible();
  await expect(page.getByText("Practice Note SC Gen 23")).toBeVisible();
  await expect(page.getByText("Offer", { exact: true })).toBeVisible();
});
