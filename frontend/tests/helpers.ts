import { expect, Browser, Page, test } from "@playwright/test";

// Shared browser-test steps. Every scenario registers a fresh synthetic client and onboards its own fixture company,
// so no application is ever created on the seeded client@demo.local companies; officer@demo.local is the only seeded
// officer, and the queue also holds other tests' applications, so rows are always located by the application id.

export const artifacts = "../.superpowers/sdd/2026-10-24-credit-route";
export const termCard = '[data-product-id="alfa_term_loan_unsecured"]';
export const lineCard = '[data-product-id="alfa_revolving_line_unsecured"]';
export const securedCard = '[data-product-id="alfa_term_loan_secured"]';
export const password = "DemoCredit2026!";

/** Registers a new synthetic client from the login page and returns its e-mail. */
export async function registerClient(page: Page, prefix = "client") {
  const email = `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}@example.test`;
  await page.goto("/");
  await page.getByRole("button", { name: "Регистрация", exact: true }).click();
  await page.getByLabel("Ваше имя").fill("Демо Предприниматель");
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page
    .getByRole("button", { name: "Создать аккаунт", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Здесь появятся ваши компании" }),
  ).toBeVisible();
  return email;
}

/** Adds a demo fixture company with every onboarding consent and waits for its source results. */
export async function onboard(page: Page, fixtureText: string) {
  await page
    .locator(".sidebar")
    .getByRole("button", { name: "Добавить компанию" })
    .click();
  await page.getByRole("button").filter({ hasText: fixtureText }).click();
  for (const checkbox of await page.getByRole("checkbox").all())
    await checkbox.check();
  await page.getByRole("button", { name: "Добавить и проверить" }).click();
  await expect(
    page.getByRole("heading", { name: "Что удалось узнать" }),
  ).toBeVisible();
}

export async function openRecommendations(page: Page) {
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await expect(page.locator(termCard)).toBeVisible();
}

export async function loginOfficer(page: Page) {
  await page.getByRole("button", { name: "Специалист", exact: true }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Очередь заявок" }),
  ).toBeVisible();
}

/** The officer works in a browser context of their own, beside the client's. */
export async function officerPage(browser: Browser) {
  const context = await browser.newContext({
    baseURL: test.info().project.use.baseURL,
    viewport: { width: 1440, height: 1000 },
  });
  const page = await context.newPage();
  await page.goto("/");
  await loginOfficer(page);
  return page;
}

export async function expectStage(page: Page, number: number, title: string) {
  await expect(
    page.getByText(`Шаг ${number} из 6`, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { level: 2, name: title, exact: true }),
  ).toBeVisible();
}

export const saveAndContinue = (page: Page) =>
  page.getByRole("button", { name: "Сохранить и продолжить" }).click();

export async function fillCompanyStage(page: Page) {
  await page.getByLabel("Сведения о компании из демо-реестра верны").check();
  await page
    .getByLabel("Фактический адрес")
    .fill("Демо-город, ул. Синтетическая, 1");
  await page
    .getByLabel("Фактическая деятельность")
    .fill("Оптовая торговля (демо)");
}

export async function fillFinanceStage(page: Page) {
  await page
    .getByRole("group", { name: "Налоговый режим" })
    .getByLabel("УСН")
    .check();
  await page.getByLabel("Число сотрудников").fill("7");
  await page
    .getByRole("group", { name: "Выручка зависит от сезона" })
    .getByLabel("Нет")
    .check();
}

export async function fillObligationsStage(page: Page, debt = "160000") {
  await page
    .getByLabel("Ежемесячные платежи по действующим кредитам и лизингу, ₽")
    .fill(debt);
  await page.getByLabel("Налоговая задолженность, ₽").fill("0");
  await page
    .getByRole("group", { name: "Есть судебные разбирательства" })
    .getByLabel("Нет")
    .check();
}

export async function fillRepresentativeStage(page: Page) {
  await page
    .getByLabel("ФИО представителя (синтетические данные)")
    .fill("Демо Представитель");
  await page.getByLabel("Подтверждаю полномочия представителя").check();
  await page.getByLabel("Сведения о владельцах указаны верно").check();
}

export const processingConsent = (page: Page) =>
  page.getByRole("checkbox", { name: /рассмотрения заявки/ });
export const bkiConsent = (page: Page) =>
  page.getByRole("checkbox", { name: /запрос кредитной истории/ });

/** On the review stage: confirms the answers, gives both consents and submits. */
export async function acceptAndSubmit(page: Page) {
  await page.getByLabel("Подтверждаю, что сведения анкеты верны").check();
  await processingConsent(page).check();
  await bkiConsent(page).check();
  await page.getByRole("button", { name: "Отправить заявку" }).click();
}

export type Profile = {
  amount?: string;
  revenue?: [string, string];
  debt: string;
  /** Declares the pledge on stage 2 (the secured product needs one). */
  pledge?: { value: string; description: string };
};

/** Completes and submits a questionnaire from a product card and waits for the check's outcome headline. */
export async function submitApplication(
  page: Page,
  card: string,
  profile: Profile,
  outcome: string,
) {
  await page
    .locator(card)
    .getByRole("button", { name: "Начать анкету" })
    .click();
  await expectStage(page, 1, "Компания");
  const id = new URL(page.url()).searchParams.get("application")!;
  expect(id).toMatch(/^[0-9a-f-]{36}$/);
  await fillCompanyStage(page);
  await saveAndContinue(page);
  await expectStage(page, 2, "Параметры");
  if (profile.amount) await page.getByLabel("Сумма, ₽").fill(profile.amount);
  if (profile.pledge) {
    const pledge = page.getByRole("group", { name: "Залог", exact: true });
    await pledge.getByLabel("Залог заявлен").check();
    await pledge.getByLabel("Недвижимость").check();
    await pledge
      .getByLabel("Заявленная стоимость, ₽")
      .fill(profile.pledge.value);
    await pledge
      .getByLabel("Описание залога")
      .fill(profile.pledge.description);
    await pledge.getByLabel("Подтверждаю собственность на залог").check();
  }
  await saveAndContinue(page);
  await expectStage(page, 3, "Бизнес и финансы");
  if (profile.revenue) {
    await page
      .getByLabel("Среднемесячная выручка за текущий период, ₽")
      .fill(profile.revenue[0]);
    await page
      .getByLabel("Среднемесячная выручка за предыдущий период, ₽")
      .fill(profile.revenue[1]);
  }
  await fillFinanceStage(page);
  await saveAndContinue(page);
  await expectStage(page, 4, "Обязательства");
  await fillObligationsStage(page, profile.debt);
  await saveAndContinue(page);
  await expectStage(page, 5, "Руководитель и владельцы");
  await fillRepresentativeStage(page);
  await saveAndContinue(page);
  await expectStage(page, 6, "Проверка и согласия");
  await acceptAndSubmit(page);
  await expect(
    page.getByRole("heading", { level: 1, name: outcome }),
  ).toBeVisible();
  return id;
}

export async function history(page: Page, id: string) {
  const response = await page.request.get(`/api/v1/applications/${id}/history`);
  expect(response.status()).toBe(200);
  return (await response.json()).items as {
    from_status: string | null;
    to_status: string;
    reason_code: string;
    reason_text: string;
  }[];
}

export async function staffDetail(page: Page, id: string) {
  const response = await page.request.get(`/api/v1/officer/applications/${id}`);
  expect(response.status()).toBe(200);
  return response.json();
}

/** Lets layout and painting catch up after a viewport change, so a capture never shows a half-resized frame. */
export const settle = (page: Page) =>
  page.evaluate(
    () =>
      new Promise<void>((done) =>
        requestAnimationFrame(() => requestAnimationFrame(() => done())),
      ),
  );

/** No page-level horizontal scroll; a dense table may scroll inside its own container. */
export async function expectNoPageOverflow(page: Page) {
  const overflow = await page.evaluate(() =>
    [...document.querySelectorAll("body *")]
      .filter((el) => !el.closest(".table-scroll"))
      .filter((el) => {
        const box = el.getBoundingClientRect();
        return box.width > 0 && box.right > innerWidth + 1;
      })
      .map((el) => `${el.tagName}.${el.className}`),
  );
  expect(overflow).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
}

/** Every visible control in the main area is at least 44px tall. */
export async function expectTouchTargets(page: Page) {
  const small = await page.evaluate(() =>
    [
      ...document.querySelectorAll(
        "main button, main a, main select, main .choice, main .check-row",
      ),
    ]
      .filter((el) => {
        const box = el.getBoundingClientRect();
        return box.width > 0 && box.height < 44;
      })
      .map((el) => `${el.tagName}.${el.className}: ${el.textContent?.trim()}`),
  );
  expect(small).toEqual([]);
}
