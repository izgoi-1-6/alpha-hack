import { test, expect } from "@playwright/test";
const artifacts = "../.superpowers/sdd/2026-10-24-credit-route";

test("seeded demo login, source details, retry and persistent refresh", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "С возвращением" }),
  ).toBeVisible();
  await page.evaluate(() => window.scrollTo(0,0));
  await page.screenshot({
    path: artifacts + "/task-2-login-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Демо-клиент", exact: true }).click();
  await page
    .getByLabel("Ваша компания", { exact: true })
    .selectOption({ label: "ООО «Демо Сильный бизнес» · 9900000017" });
  await expect(
    page.getByRole("heading", { name: "ООО «Демо Сильный бизнес»" }),
  ).toBeVisible();
  await expect(page.getByText("800 000 ₽", { exact: true })).toBeVisible();
  await page.evaluate(() => window.scrollTo(0,0));
  await page.screenshot({
    path: artifacts + "/task-2-company-desktop.png",
    fullPage: true,
  });
  expect(await page.evaluate(() => document.cookie)).not.toContain(
    "credit_route_session",
  );
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "ООО «Демо Сильный бизнес»" }),
  ).toBeVisible();
  await page
    .getByLabel("Ваша компания", { exact: true })
    .selectOption({ label: "ООО «Демо Неактивный бизнес» · 9900000049" });
  await expect(
    page.getByText("Компания доступна только для просмотра"),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Добавить компанию", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Начнём с вашего бизнеса" }),
  ).toBeVisible();
  await page
    .getByRole("button")
    .filter({ hasText: "Реестр недоступен" })
    .click();
  await expect(page.getByLabel("ИНН компании или ИП")).toHaveValue(
    "9900000063",
  );
  await page.evaluate(() => window.scrollTo(0,0));
  await page.screenshot({
    path: artifacts + "/task-2-onboarding-desktop.png",
    fullPage: true,
  });
});

test("mobile registration, explicit consents, source recovery, reload, errors and logout", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Регистрация", exact: true }).click();
  await page.getByLabel("Ваше имя").fill("Демо Предприниматель");
  await page
    .getByLabel("Электронная почта")
    .fill(`browser-${Date.now()}@example.test`);
  await page.getByLabel("Пароль", { exact: true }).fill("DemoCredit2026!");
  await page
    .getByRole("button", { name: "Создать аккаунт", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Добавить компанию", exact: true })
    .last()
    .click();
  await expect(
    page.getByRole("button", { name: "Добавить и проверить" }),
  ).toBeDisabled();
  await page
    .getByRole("button")
    .filter({ hasText: "Реестр недоступен" })
    .click();
  for (const checkbox of await page.getByRole("checkbox").all())
    await checkbox.check();
  await page.evaluate(() => window.scrollTo(0,0));
  await page.screenshot({
    path: artifacts + "/task-2-onboarding-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Добавить и проверить" }).click();
  await expect(
    page.getByText("Реестр временно недоступен", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("Реестр временно недоступен", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Повторить проверку" }).click();
  await expect(
    page.getByText("Действующая компания", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("Действующая компания", { exact: true }),
  ).toBeVisible();
  await page.evaluate(() => window.scrollTo(0,0));
  await page.screenshot({
    path: artifacts + "/task-2-company-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.route("**/api/v1/companies", (route) => route.abort());
  await page.reload();
  await expect(page.getByRole("alert")).toContainText("Нет связи с сервером");
  await page.unroute("**/api/v1/companies");
  await page.getByRole("button", { name: "Повторить попытку" }).click();
  await expect(
    page.getByText("Действующая компания", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Открыть меню" }).click();
  await page.getByRole("button", { name: "Выйти из аккаунта" }).click();
  await expect(
    page.getByRole("heading", { name: "С возвращением" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "С возвращением" }),
  ).toBeVisible();
});
