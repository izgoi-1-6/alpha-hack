import { expect } from "@playwright/test";
import { test } from "./fixtures";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import {
  acceptAndSubmit,
  authorityDialog,
  DEMO_EMAIL,
  DEMO_WORDS,
  expectNoDemoWording,
  expectStage,
  fillCompanyStage,
  fillFinanceStage,
  fillObligationsStage,
  fillParametersStage,
  fillRepresentativeStage,
  LATIN_DEMO,
  officerPage,
  registerClient,
  saveAndContinue,
  termCard,
} from "./helpers";

// The user removed every «демо»/«демонстрац…»/«имитац…» wording from the app. Two checks: what the
// browser renders on the main pages for a client and for an officer, and the frontend source itself. The approved
// application and the Alfa-Business hand-off page are walked by the document journey in documents.spec.ts.

test("no demo wording on the main pages: login, onboarding with the Госуслуги dialog, product choice, every questionnaire stage, status, the officer's queue and review", async ({
  page,
  browser,
}) => {
  test.setTimeout(150_000);
  await page.goto("/");
  await expectNoDemoWording(page);
  await page.getByRole("button", { name: "Регистрация", exact: true }).click();
  await expectNoDemoWording(page);

  await registerClient(page, "wording");
  await expectNoDemoWording(page);
  await page
    .locator(".sidebar")
    .getByRole("button", { name: "Добавить компанию" })
    .click();
  await expectNoDemoWording(page);
  await page.getByRole("button").filter({ hasText: "Сильный бизнес" }).click();
  await page
    .getByRole("button", { name: "Подтвердить через Госуслуги" })
    .click();
  const dialog = authorityDialog(page);
  await expect(dialog).toContainText("Соколов Андрей Викторович");
  await expectNoDemoWording(page);
  await dialog.getByRole("button", { name: "Подтвердить" }).click();
  await expectNoDemoWording(page);
  for (const checkbox of await page
    .locator("#onboarding-consents")
    .getByRole("checkbox")
    .all())
    await checkbox.check();
  await page.getByRole("button", { name: "Добавить и проверить" }).click();
  await expect(
    page.getByRole("heading", { name: "Что удалось узнать" }),
  ).toBeVisible();
  await expectNoDemoWording(page);

  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await expect(page.locator(termCard)).toBeVisible();
  await expectNoDemoWording(page);
  await page
    .locator(termCard)
    .getByRole("button", { name: "Начать анкету" })
    .click();
  await expectStage(page, 1, "Компания");
  const id = new URL(page.url()).searchParams.get("application");
  expect(id).toMatch(/^[0-9a-f-]{36}$/);
  await expectNoDemoWording(page);
  const stages: [number, string, () => Promise<void>][] = [
    [2, "Параметры", () => fillCompanyStage(page)],
    [3, "Бизнес и финансы", () => fillParametersStage(page)],
    [4, "Обязательства", () => fillFinanceStage(page)],
    [5, "Руководитель и владельцы", () => fillObligationsStage(page)],
    [6, "Проверка и согласия", () => fillRepresentativeStage(page)],
  ];
  for (const [number, title, fill] of stages) {
    await fill();
    await saveAndContinue(page);
    await expectStage(page, number, title);
    await expectNoDemoWording(page);
  }
  await acceptAndSubmit(page);
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Заявка предварительно одобрена",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Документы по заявке" }),
  ).toBeVisible();
  await expectNoDemoWording(page);
  await page.goto(`/alfa-business/${id}`);
  await expect(
    page.getByRole("heading", { level: 1, name: "Переход пока недоступен" }),
  ).toBeVisible();
  await expectNoDemoWording(page);
  await page
    .locator(".sidebar")
    .getByRole("button", { name: "Мои заявки" })
    .click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Мои заявки" }),
  ).toBeVisible();
  await expectNoDemoWording(page);

  const officer = await officerPage(browser);
  await expect(officer.locator("main table")).toBeVisible();
  await expectNoDemoWording(officer);
  await officer.goto(`/?application=${id}`);
  await expect(
    officer.getByRole("region", { name: "Решение по заявке" }),
  ).toBeVisible();
  await expect(
    officer.getByRole("region", { name: "Источники данных" }),
  ).toBeVisible();
  await expectNoDemoWording(officer);
  await officer.goto("/?view=applications");
  await expect(
    officer.getByRole("heading", { level: 1, name: "Нет доступа" }),
  ).toBeVisible();
  await expectNoDemoWording(officer);
  await officer.close();
});

/** Latin "demo" that the app keeps by the binding exceptions: seeded e-mails, the seed password the quick-login
 * buttons send, the backend's fixture route and the notification channel identifier (never rendered). */
const ALLOWED_LATIN = [
  DEMO_EMAIL,
  /DemoCredit2026!/g,
  /"\/demo\/fixtures"/g,
  /"demo_in_app"/g,
];

function sourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    return statSync(path).isDirectory() ? sourceFiles(path) : [path];
  });
}

test("no demo wording in the frontend source: Russian words without exception, Latin only for the named identifiers", () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const files = [...sourceFiles(join(root, "src")), join(root, "index.html")];
  expect(files.length).toBeGreaterThan(40);
  const russian: string[] = [];
  const latin: string[] = [];
  for (const file of files) {
    readFileSync(file, "utf-8")
      .split("\n")
      .forEach((line, index) => {
        const place = `${relative(root, file)}:${index + 1}: ${line.trim()}`;
        if (DEMO_WORDS.test(line)) russian.push(place);
        if (
          LATIN_DEMO.test(
            ALLOWED_LATIN.reduce(
              (text, allowed) => text.replace(allowed, ""),
              line,
            ),
          )
        )
          latin.push(place);
      });
  }
  expect(russian).toEqual([]);
  expect(latin).toEqual([]);
});
