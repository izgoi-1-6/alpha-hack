import { expect, Page } from "@playwright/test";
import { test } from "./fixtures";
import {
  documentsCard,
  logOut,
  officerPage,
  onboard,
  registerClient,
  requirementRow,
  signIn,
  submitApplication,
  termCard,
  uploadDocument,
} from "./helpers";
import { pdfFile } from "./files";

// End-to-end journey against the real app: who may see and do what. A fresh synthetic client owns an
// application with a document; another fresh client, officer@demo.local and a signed-out visitor try to reach it.
// The seeded client@demo.local's company is only read (refused), never changed.

const ORIGIN = "http://localhost:5173";
const seededCompany = "e230a446-129b-570f-b450-3cd8f7ddc8e5";
const heading = (page: Page, name: string) =>
  page.getByRole("heading", { level: 1, name });

/** A command as the browser would send it: same-origin, with an idempotency key. */
const command = (page: Page, path: string, data: unknown, origin: string | null = ORIGIN) =>
  page.request.post(path, {
    data,
    headers: {
      ...(origin ? { Origin: origin } : {}),
      "Idempotency-Key": crypto.randomUUID(),
    },
  });
const status = async (page: Page, path: string) => (await page.request.get(path)).status();

test("journey 6 — cross-client and cross-role access: another client, the officer and a signed-out visitor are refused everything they do not own or may not do", async ({
  page,
  browser,
}) => {
  test.setTimeout(240_000);
  // The owner: a preliminarily approved application with an uploaded statement.
  const owner = await registerClient(page, "journey-access-owner");
  await onboard(page, "Сильный бизнес");
  const companyId = new URL(page.url()).searchParams.get("company")!;
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await expect(page.locator(termCard)).toBeVisible();
  const id = await submitApplication(page, termCard, { debt: "160000" }, "Заявка предварительно одобрена");
  await uploadDocument(requirementRow(documentsCard(page), "BANK_STATEMENT"), pdfFile("Выписка.pdf"));
  const { application } = await (await page.request.get(`/api/v1/applications/${id}`)).json();
  const checklist = await (await page.request.get(`/api/v1/applications/${id}/documents`)).json();
  const downloadUrl = checklist.items[0].download_url as string;
  const owned = [
    `/api/v1/companies/${companyId}`,
    `/api/v1/companies/${companyId}/precheck`,
    `/api/v1/companies/${companyId}/recommendations/${application.recommendation_snapshot_id}`,
    `/api/v1/applications/${id}`,
    `/api/v1/applications/${id}/history`,
    `/api/v1/applications/${id}/dialog`,
    `/api/v1/applications/${id}/documents`,
    downloadUrl,
  ];
  for (const path of owned) expect(await status(page, path), path).toBe(200);
  // The session is a server cookie (HttpOnly, SameSite=Lax); nothing is kept in the browser's storage.
  const cookie = (await page.context().cookies()).find((entry) => entry.name === "credit_route_session")!;
  expect(cookie).toMatchObject({ httpOnly: true, sameSite: "Lax" });
  expect(await page.evaluate(() => Object.keys(window.localStorage))).toEqual([]);
  // A command without the exact Origin is refused before anything else, even for the owner.
  expect((await command(page, `/api/v1/applications/${id}/cancel`, { version: application.version, reason: "Проверка" }, "http://evil.example")).status()).toBe(403);

  // Another client: not found, whatever the way in (pages, reads, commands, files), and no officer data.
  await logOut(page);
  await registerClient(page, "journey-access-other");
  await page.goto(`/?application=${id}`);
  await expect(heading(page, "Заявка не найдена")).toBeVisible();
  await page.goto(`/alfa-business/${id}`);
  await expect(heading(page, "Страница недоступна")).toBeVisible();
  await page.goto(`/?company=${companyId}`);
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.locator("main")).not.toContainText("Сильный бизнес");
  for (const path of [...owned, `/api/v1/companies/${seededCompany}`])
    expect(await status(page, path), path).toBe(404);
  const cancel = await command(page, `/api/v1/applications/${id}/cancel`, {
    version: application.version,
    reason: "Чужая заявка",
  });
  expect(cancel.status()).toBe(404);
  expect((await cancel.json()).error.code).toBe("APPLICATION_NOT_FOUND");
  expect(await status(page, "/api/v1/officer/applications")).toBe(403);
  const claim = await command(page, `/api/v1/officer/applications/${id}/claim`, { version: application.version });
  expect(claim.status()).toBe(403);
  expect((await claim.json()).error.code).toBe("OFFICER_REQUIRED");
  await page.goto("/?view=queue");
  await expect(heading(page, "Нет доступа")).toBeVisible();
  await expect(page.locator("main table")).toHaveCount(0);

  // The officer: the staff view and the files of any application, but no client page or client command.
  const officer = await officerPage(browser);
  expect(await status(officer, `/api/v1/officer/applications/${id}`)).toBe(200);
  expect(await status(officer, downloadUrl)).toBe(200);
  for (const path of [`/api/v1/applications/${id}`, "/api/v1/companies"]) {
    const refused = await officer.request.get(path);
    expect(refused.status(), path).toBe(403);
    expect((await refused.json()).error.code).toBe("CLIENT_REQUIRED");
  }
  const create = await command(officer, "/api/v1/applications", {
    company_id: companyId,
    product_id: "alfa_term_loan_unsecured",
    recommendation_snapshot_id: application.recommendation_snapshot_id,
  });
  expect(create.status()).toBe(403);
  await officer.goto("/?view=applications");
  await expect(heading(officer, "Нет доступа")).toBeVisible();
  await officer.goto(`/alfa-business/${id}`);
  await expect(heading(officer, "Нет доступа")).toBeVisible();
  await officer.goto(`/?company=${companyId}`);
  await expect(heading(officer, "Нет доступа")).toBeVisible();
  await expect(officer.locator("main")).not.toContainText("Сильный бизнес");

  // Signed out: the API asks for a session; the page asks for a sign-in at a clean address (the next account never
  // lands on the previous one's page), after which the owner starts at home and finds the application in the list.
  await logOut(page);
  for (const path of [`/api/v1/applications/${id}`, downloadUrl, "/api/v1/officer/applications"])
    expect(await status(page, path), path).toBe(401);
  await page.goto(`/?application=${id}`);
  await expect(page.getByRole("heading", { name: "С возвращением" })).toBeVisible();
  expect(new URL(page.url()).search).toBe("");
  await signIn(page, owner);
  await expect(page.getByRole("heading", { name: "ООО «Сильный бизнес»" })).toBeVisible();
  await page.locator(".sidebar").getByRole("button", { name: "Мои заявки" }).click();
  await page.locator(".application-row").getByRole("link").click();
  await expect(heading(page, "Заявка предварительно одобрена")).toBeVisible();
  expect(new URL(page.url()).searchParams.get("application")).toBe(id);
});
