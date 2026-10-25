import { test, expect, Page } from "@playwright/test";
import {
  acceptAndSubmit,
  artifacts,
  bkiConsent,
  expectNoPageOverflow,
  expectStage,
  expectTouchTargets,
  fillCompanyStage,
  fillFinanceStage,
  fillObligationsStage,
  fillRepresentativeStage,
  history,
  lineCard,
  onboard,
  openRecommendations,
  processingConsent,
  registerClient,
  saveAndContinue,
  securedCard,
  termCard,
} from "./helpers";

async function startDraft(page: Page, card: string) {
  await page
    .locator(card)
    .getByRole("button", { name: "Начать анкету" })
    .click();
  await expectStage(page, 1, "Компания");
  const id = new URL(page.url()).searchParams.get("application");
  expect(id).toMatch(/^[0-9a-f-]{36}$/);
  return id!;
}

// Stages 1–5 with a low-risk profile, ending on the review stage.
async function completeQuestionnaire(page: Page, check?: () => Promise<void>) {
  await fillCompanyStage(page);
  await saveAndContinue(page);
  await expectStage(page, 2, "Параметры");
  await check?.();
  await saveAndContinue(page);
  await expectStage(page, 3, "Бизнес и финансы");
  await fillFinanceStage(page);
  await check?.();
  await saveAndContinue(page);
  await expectStage(page, 4, "Обязательства");
  await fillObligationsStage(page);
  await saveAndContinue(page);
  await expectStage(page, 5, "Руководитель и владельцы");
  await fillRepresentativeStage(page);
  await saveAndContinue(page);
  await expectStage(page, 6, "Проверка и согласия");
}

test("strong company: card → saved six-stage questionnaire → reload resumes → explicit consents → preliminary approval with distinct amounts and labelled simulated notifications", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await registerClient(page, "app");
  await onboard(page, "Сильный бизнес");
  await openRecommendations(page);
  // Informational research items never get an application action.
  await page.getByText("Исследовательский каталог", { exact: false }).click();
  await expect(
    page.locator(".research-catalog").getByRole("button"),
  ).toHaveCount(0);
  await expect(
    page.locator(termCard).getByRole("button", { name: "Начать анкету" }),
  ).toBeVisible();
  const id = await startDraft(page, termCard);
  await expect(page.locator(".wizard-header")).toContainText(
    "Кредит одной суммой без залога",
  );
  await expect(page.locator(".wizard-header")).toContainText(
    "ООО «Демо Сильный бизнес»",
  );

  await fillCompanyStage(page);
  await saveAndContinue(page);
  await expectStage(page, 2, "Параметры");
  // Focus moves to the new stage heading and the save is announced.
  await expect(
    page.getByRole("heading", { level: 2, name: "Параметры" }),
  ).toBeFocused();
  await expect(page.locator(".application-live")).toContainText("Сохранено");
  // Stage 2 is prefilled from the recommendation need.
  await expect(
    page
      .getByRole("group", { name: "Цель финансирования" })
      .getByLabel("Пополнение оборотных средств"),
  ).toBeChecked();
  await expect(page.getByLabel("Сумма, ₽")).toHaveValue("1500000");
  await expect(page.getByLabel("Срок, мес.")).toHaveValue("12");
  await page.getByLabel("Сумма, ₽").fill("2000000");
  await saveAndContinue(page);

  await expectStage(page, 3, "Бизнес и финансы");
  // Source-prefilled finance values carry their source tag; editing one routes it to an officer.
  const revenue = page.getByLabel(
    "Среднемесячная выручка за текущий период, ₽",
  );
  await expect(revenue).toHaveValue("800000");
  const revenueField = page.locator(".field").filter({ has: revenue });
  await expect(revenueField).toContainText("Демо-источник оборотов");
  await expect(revenueField).toContainText("800 000 ₽");
  await expect(revenueField).toContainText("Демо · имитация");
  await revenue.fill("900000");
  await expect(revenueField).toContainText("проверит кредитный специалист");
  await revenue.fill("800000");
  await expect(revenueField).not.toContainText("проверит кредитный специалист");
  await fillFinanceStage(page);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: `${artifacts}/task-4b-wizard-desktop.png`,
    fullPage: true,
  });
  await saveAndContinue(page);
  await expectStage(page, 4, "Обязательства");

  // A reload mid-wizard resumes at the saved stage with the saved answers.
  await page.reload();
  await expectStage(page, 4, "Обязательства");
  await fillObligationsStage(page);
  await saveAndContinue(page);
  await expectStage(page, 5, "Руководитель и владельцы");
  await fillRepresentativeStage(page);
  await saveAndContinue(page);
  await expectStage(page, 6, "Проверка и согласия");

  const review = page.locator(".review");
  await expect(review).toContainText("Демо-город, ул. Синтетическая, 1");
  await expect(review).toContainText("2 000 000 ₽");
  await expect(review).toContainText("УСН");
  await expect(review).toContainText("160 000 ₽");
  await expect(review).toContainText("Демо Представитель");

  // Two separate consents, unchecked by default, with their exact versions; submission is blocked without them.
  await expect(processingConsent(page)).not.toBeChecked();
  await expect(bkiConsent(page)).not.toBeChecked();
  await expect(page.getByText("Версия demo-consent-v1")).toHaveCount(2);
  const submit = page.getByRole("button", { name: "Отправить заявку" });
  await expect(submit).toBeDisabled();
  await page.getByLabel("Подтверждаю, что сведения анкеты верны").check();
  await expect(submit).toBeDisabled();
  await processingConsent(page).check();
  await expect(submit).toBeDisabled();
  await bkiConsent(page).check();
  await expect(submit).toBeEnabled();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: `${artifacts}/task-4b-review-consent.png`,
    fullPage: true,
  });

  // The review is editable: jump back to a stage, then return; consents are never kept between visits.
  await page.getByRole("button", { name: "Изменить шаг 2: Параметры" }).click();
  await expectStage(page, 2, "Параметры");
  await expect(page.getByLabel("Сумма, ₽")).toHaveValue("2000000");
  await page
    .getByRole("navigation", { name: "Шаги анкеты" })
    .getByRole("button", { name: /Шаг 6: Проверка и согласия/ })
    .click();
  await expectStage(page, 6, "Проверка и согласия");
  await expect(
    page.getByLabel("Подтверждаю, что сведения анкеты верны"),
  ).toBeChecked();
  await expect(processingConsent(page)).not.toBeChecked();
  await expect(bkiConsent(page)).not.toBeChecked();
  await expect(submit).toBeDisabled();
  await processingConsent(page).check();
  await bkiConsent(page).check();
  await submit.click();

  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Заявка предварительно одобрена",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Заявка предварительно одобрена",
    }),
  ).toBeFocused();
  await expect(page.locator(".application-live")).toContainText(
    "Заявка отправлена",
  );
  const requested = page.getByRole("group", { name: "Запрошенная сумма" });
  const indicative = page.getByRole("group", {
    name: "Предварительная оценка лимита",
  });
  const preapproved = page.getByRole("group", {
    name: "Предварительно одобрено",
  });
  await expect(requested).toContainText("2 000 000 ₽");
  await expect(indicative).toContainText("2 400 000 ₽");
  await expect(indicative).toContainText("не предложение");
  await expect(page.locator(".result-meta")).toContainText(
    "Расчёт демо-скоринга — не предложение",
  );
  await expect(preapproved).toContainText("2 000 000 ₽");
  await expect(preapproved).toContainText("не окончательное решение");
  await expect(page.locator(".status-next")).toContainText(
    "Подготовьте документы",
  );

  const timeline = page.getByRole("list", { name: "История заявки" });
  await expect(timeline.getByRole("listitem")).toHaveCount(3);
  await expect(timeline.getByText("Демо · имитация уведомления")).toHaveCount(
    3,
  );
  await expect(timeline).toContainText(
    "Заявка предварительно одобрена на 2 000 000 ₽",
  );
  expect((await history(page, id)).map((item) => item.to_status)).toEqual([
    "DRAFT",
    "CHECKING",
    "PREAPPROVED",
  ]);
  // Only the server's allowed actions are offered.
  await expect(
    page.getByRole("button", { name: "Повторить проверку" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Отменить заявку" }),
  ).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: `${artifacts}/task-4b-status-timeline.png`,
    fullPage: true,
  });

  // Another client cannot open this application's URL.
  await page.getByRole("button", { name: "Выйти из аккаунта" }).click();
  await registerClient(page, "app");
  await page.goto(`/?application=${id}`);
  await expect(
    page.getByRole("heading", { level: 1, name: "Заявка не найдена" }),
  ).toBeVisible();
  await expect(page.getByText("Демо Сильный бизнес")).toHaveCount(0);
  expect((await page.request.get(`/api/v1/applications/${id}`)).status()).toBe(
    404,
  );
});

test("unavailable demo BKI: lost submit and retry responses replay their keys; WAIT_EXTERNAL recovers with one decision", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await registerClient(page, "app");
  await onboard(page, "БКИ недоступно");
  await openRecommendations(page);
  const id = await startDraft(page, termCard);
  await completeQuestionnaire(page);

  // The real API commits each first command, but its response is lost on the way back.
  const commands: Record<string, { key?: string; body: unknown }[]> = {
    submit: [],
    "retry-check": [],
  };
  await page.route(
    /\/api\/v1\/applications\/[^/]+\/(submit|retry-check)$/,
    async (route) => {
      const action = route.request().url().endsWith("/submit")
        ? "submit"
        : "retry-check";
      const response = await route.fetch();
      commands[action].push({
        key: route.request().headers()["idempotency-key"],
        body: route.request().postDataJSON(),
      });
      if (commands[action].length === 1) await route.abort();
      else await route.fulfill({ response });
    },
  );
  await acceptAndSubmit(page);
  await expect(page.getByRole("alert")).toContainText("Нет связи с сервером");
  await page.getByRole("button", { name: "Отправить заявку" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Ждём ответа демо-источника" }),
  ).toBeVisible();
  await expect(page.locator(".status-pill")).toHaveText("Ждём демо-источник");
  await expect(page.locator(".status-result")).toContainText(
    "Демо-БКИ временно недоступно",
  );

  await page.getByRole("button", { name: "Повторить проверку" }).click();
  await expect(page.getByRole("alert")).toContainText("Нет связи с сервером");
  await page.getByRole("button", { name: "Повторить проверку" }).click();
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Заявка предварительно одобрена",
    }),
  ).toBeVisible();
  await expect(page.locator(".application-live")).toContainText(
    "Предварительно одобрена",
  );
  await expect(
    page.getByRole("group", { name: "Предварительно одобрено" }),
  ).toContainText("1 500 000 ₽");

  expect(commands.submit).toHaveLength(2);
  expect(commands.submit[1]).toEqual(commands.submit[0]);
  expect(commands["retry-check"]).toHaveLength(2);
  expect(commands["retry-check"][1]).toEqual(commands["retry-check"][0]);
  // One submission, one recovery and one decision despite the repeated clicks.
  expect(
    (await history(page, id)).map((item) => [
      item.from_status,
      item.to_status,
      item.reason_code,
    ]),
  ).toEqual([
    [null, "DRAFT", "CREATED"],
    ["DRAFT", "CHECKING", "SUBMITTED"],
    ["CHECKING", "WAIT_EXTERNAL", "R4"],
    ["WAIT_EXTERNAL", "CHECKING", "RETRY_CHECK"],
    ["CHECKING", "PREAPPROVED", "R8"],
  ]);
  await expect(
    page.getByRole("list", { name: "История заявки" }).getByRole("listitem"),
  ).toHaveCount(5);
  await expect(
    page.getByRole("button", { name: "Повторить проверку" }),
  ).toHaveCount(0);

  // Cancelling from the status page moves focus to the new status heading.
  await page.getByRole("button", { name: "Отменить заявку" }).click();
  await page
    .getByLabel("Причина отмены")
    .fill("Проверка отмены после одобрения");
  await page.getByRole("button", { name: "Да, отменить заявку" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Заявка отменена" }),
  ).toBeFocused();
});

test("My Applications lists every application with status and next step; cancel asks for confirmation", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await registerClient(page, "app");
  await onboard(page, "Сильный бизнес");
  await openRecommendations(page);
  const termId = await startDraft(page, termCard);
  await page
    .locator(".sidebar")
    .getByRole("button", { name: "Мои компании" })
    .click();
  await openRecommendations(page);
  const lineId = await startDraft(page, lineCard);
  // Leaving through the wizard's back link saves the open stage's edits first.
  await page
    .getByLabel("Фактический адрес")
    .fill("Демо-город, пр. Черновой, 2");
  await page.getByRole("button", { name: "← Мои заявки" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Мои заявки" }),
  ).toBeVisible();
  const saved = await (
    await page.request.get(`/api/v1/applications/${lineId}`)
  ).json();
  expect(saved.application.answers.actual_address).toBe(
    "Демо-город, пр. Черновой, 2",
  );
  const rows = page.locator(".application-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText(
    "Возобновляемая кредитная линия без залога",
  );
  await expect(rows.nth(1)).toContainText("Кредит одной суммой без залога");
  for (const row of await rows.all()) {
    await expect(row).toContainText("ООО «Демо Сильный бизнес»");
    await expect(row.locator(".status-pill")).toHaveText("Черновик");
    await expect(row).toContainText("Продолжите анкету: шаг 1 из 6");
  }

  await rows
    .nth(1)
    .getByRole("link", { name: /Кредит одной суммой без залога/ })
    .click();
  await expectStage(page, 1, "Компания");
  await expect(page).toHaveURL(new RegExp(`application=${termId}`));
  await page.getByRole("button", { name: "Отменить заявку" }).click();
  await expect(page.getByLabel("Причина отмены")).toBeFocused();
  await page.getByRole("button", { name: "Не отменять" }).click();
  await expect(page.getByLabel("Причина отмены")).toHaveCount(0);
  await expectStage(page, 1, "Компания");
  await page.getByRole("button", { name: "Отменить заявку" }).click();
  const confirm = page.getByRole("button", { name: "Да, отменить заявку" });
  await expect(confirm).toBeDisabled();
  await page.getByLabel("Причина отмены").fill("Выбрали другой продукт");
  await confirm.click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Заявка отменена" }),
  ).toBeVisible();
  const timeline = page.getByRole("list", { name: "История заявки" });
  await expect(timeline.getByRole("listitem")).toHaveCount(2);
  await expect(timeline).toContainText("Выбрали другой продукт");
  await expect(
    page.getByRole("button", { name: "Отменить заявку" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Повторить проверку" }),
  ).toHaveCount(0);

  await page.getByRole("button", { name: "Мои заявки" }).first().click();
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0).locator(".status-pill")).toHaveText("Черновик");
  await expect(rows.nth(1).locator(".status-pill")).toHaveText("Отменена");
  await expect(rows.nth(1)).toContainText(
    "Можно начать новую заявку из подбора",
  );
  const { application } = await (
    await page.request.get(`/api/v1/applications/${termId}`)
  ).json();
  expect(application.status).toBe("CANCELLED");
});

test("open-stage edits are saved when leaving through the sidebar or the browser history", async ({
  page,
}) => {
  await registerClient(page, "app");
  await onboard(page, "Сильный бизнес");
  await openRecommendations(page);
  const id = await startDraft(page, termCard);
  const reopen = async () => {
    await page
      .locator(".sidebar")
      .getByRole("button", { name: "Мои заявки" })
      .click();
    await page.locator(".application-row").getByRole("link").click();
    await expectStage(page, 1, "Компания");
  };

  // A sidebar destination: the edit is saved before the company page opens.
  await page.getByLabel("Фактический адрес").fill("Демо-город, ул. Боковая, 3");
  await page
    .locator(".sidebar")
    .getByRole("button", { name: "Мои компании" })
    .click();
  await expect(
    page.getByRole("heading", { name: "ООО «Демо Сильный бизнес»" }),
  ).toBeVisible();
  await reopen();
  await expect(page.getByLabel("Фактический адрес")).toHaveValue(
    "Демо-город, ул. Боковая, 3",
  );

  // Browser Back: saved as well; Forward reopens the application.
  await page
    .getByLabel("Фактическая деятельность")
    .fill("Розничная торговля (демо)");
  await page.goBack();
  await expect(
    page.getByRole("heading", { level: 1, name: "Мои заявки" }),
  ).toBeVisible();
  await page.goForward();
  await expectStage(page, 1, "Компания");
  await expect(page.getByLabel("Фактическая деятельность")).toHaveValue(
    "Розничная торговля (демо)",
  );
  const { application } = await (
    await page.request.get(`/api/v1/applications/${id}`)
  ).json();
  expect(application.answers.actual_address).toBe("Демо-город, ул. Боковая, 3");
  expect(application.answers.actual_activity).toBe("Розничная торговля (демо)");
  expect(application.current_stage).toBe(1);
});

test("a value that cannot be saved is never dropped silently: stay and fix, or leave without that field", async ({
  page,
}) => {
  await registerClient(page, "app");
  await onboard(page, "Сильный бизнес");
  await openRecommendations(page);
  const id = await startDraft(page, termCard);
  await fillCompanyStage(page);
  await saveAndContinue(page);
  await expectStage(page, 2, "Параметры");
  const amount = page.getByLabel("Сумма, ₽");
  const prompt = page.getByRole("dialog", {
    name: "Это значение нельзя сохранить",
  });
  await amount.fill("2 000 000 руб");
  await page.getByLabel("Срок, мес.").fill("18");

  // Stage Back: the customer chooses to stay; the value and the other edit are kept.
  await page.getByRole("button", { name: "← Назад" }).click();
  await expect(prompt).toContainText("Сумма, ₽");
  await prompt.getByRole("button", { name: "Остаться и исправить" }).click();
  await expect(prompt).toHaveCount(0);
  await expectStage(page, 2, "Параметры");
  await expect(amount).toHaveValue("2 000 000 руб");
  await expect(amount).toBeFocused();

  // Browser Back asks the same question; staying puts the application address back.
  await page.goBack();
  await prompt.getByRole("button", { name: "Остаться и исправить" }).click();
  await expect(page).toHaveURL(new RegExp(`application=${id}`));
  await expectStage(page, 2, "Параметры");
  await expect(amount).toHaveValue("2 000 000 руб");

  // Leaving without that field still saves the valid edit.
  await page
    .locator(".sidebar")
    .getByRole("button", { name: "Мои заявки" })
    .click();
  await prompt
    .getByRole("button", { name: "Перейти, не сохраняя это поле" })
    .click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Мои заявки" }),
  ).toBeVisible();
  const { application } = await (
    await page.request.get(`/api/v1/applications/${id}`)
  ).json();
  expect(application.answers.term_months).toBe(18);
  expect(application.answers.requested_amount_rub).toBe(1500000);
});

test("a save from an outdated tab gets the stale-version reply: the page reloads, says so and keeps the unsaved edit", async ({
  page,
  context,
}) => {
  await registerClient(page, "app");
  await onboard(page, "Сильный бизнес");
  await openRecommendations(page);
  const id = await startDraft(page, termCard);
  await fillCompanyStage(page);
  await saveAndContinue(page);
  await expectStage(page, 2, "Параметры");

  const other = await context.newPage();
  await other.goto(page.url());
  await expectStage(other, 2, "Параметры");
  await page.getByLabel("Сумма, ₽").fill("2100000");
  await saveAndContinue(page);
  await expectStage(page, 3, "Бизнес и финансы");

  await other.getByLabel("Срок, мес.").fill("18");
  await saveAndContinue(other);
  await expect(other.getByRole("alert")).toContainText(
    "Заявка изменилась в другой вкладке",
  );
  await expectStage(other, 2, "Параметры");
  await expect(other.getByLabel("Сумма, ₽")).toHaveValue("2100000");
  await expect(other.getByLabel("Срок, мес.")).toHaveValue("18");
  await saveAndContinue(other);
  await expectStage(other, 3, "Бизнес и финансы");
  const { application } = await (
    await page.request.get(`/api/v1/applications/${id}`)
  ).json();
  expect(application.answers.requested_amount_rub).toBe(2100000);
  expect(application.answers.term_months).toBe(18);
  await other.close();
});

test("submitting a second draft for a product already in progress explains the conflict and links to the active application", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await registerClient(page, "app");
  await onboard(page, "Сильный бизнес");
  await openRecommendations(page);
  const first = await startDraft(page, termCard);
  await page
    .locator(".sidebar")
    .getByRole("button", { name: "Мои компании" })
    .click();
  await openRecommendations(page);
  const second = await startDraft(page, termCard);
  await completeQuestionnaire(page);

  await page.goto(`/?application=${first}`);
  await expectStage(page, 1, "Компания");
  await completeQuestionnaire(page);
  await acceptAndSubmit(page);
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Заявка предварительно одобрена",
    }),
  ).toBeVisible();

  await page.goto(`/?application=${second}`);
  await expectStage(page, 6, "Проверка и согласия");
  await acceptAndSubmit(page);
  await expect(page.getByRole("alert")).toContainText(
    "уже есть заявка в работе",
  );
  await expect(page.locator(".review")).toContainText(
    "Демо-город, ул. Синтетическая, 1",
  );
  await page.getByRole("button", { name: "Открыть заявку в работе" }).click();
  await expect(page).toHaveURL(new RegExp(`application=${first}`));
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Заявка предварительно одобрена",
    }),
  ).toBeVisible();
  const { application } = await (
    await page.request.get(`/api/v1/applications/${second}`)
  ).json();
  expect(application.status).toBe("DRAFT");
});

test("secured product: an unknown pledge must be declared before submission", async ({
  page,
}) => {
  await registerClient(page, "app");
  await onboard(page, "Сильный бизнес");
  await openRecommendations(page);
  await expect(page.locator(securedCard)).toContainText("Нужны сведения");
  await startDraft(page, securedCard);
  await page
    .getByRole("navigation", { name: "Шаги анкеты" })
    .getByRole("button", { name: /Шаг 6: Проверка и согласия/ })
    .click();
  await expectStage(page, 6, "Проверка и согласия");
  const blockers = page.locator(".review-blockers");
  await expect(blockers).toContainText("Залог");
  await expect(
    page.getByRole("button", { name: "Отправить заявку" }),
  ).toBeDisabled();

  await blockers.getByRole("button", { name: /Залог/ }).click();
  await expectStage(page, 2, "Параметры");
  const pledge = page.getByRole("group", { name: "Залог", exact: true });
  await expect(pledge).toContainText("Для кредита с залогом");
  await pledge.getByLabel("Залог заявлен").check();
  await pledge.getByLabel("Недвижимость").check();
  await pledge.getByLabel("Заявленная стоимость, ₽").fill("4000000");
  await pledge.getByLabel("Описание залога").fill("Демо склад");
  await pledge.getByLabel("Подтверждаю собственность на залог").check();
  await page
    .getByRole("navigation", { name: "Шаги анкеты" })
    .getByRole("button", { name: /Шаг 6: Проверка и согласия/ })
    .click();
  await expectStage(page, 6, "Проверка и согласия");
  await expect(blockers).not.toContainText("Залог");
  await expect(page.locator(".review")).toContainText("Недвижимость");
  await expect(page.locator(".review")).toContainText("4 000 000 ₽");
});

test("fault injection: a stale recommendation on create and on submit is explained and offers a recalculation", async ({
  page,
}) => {
  // The live catalog only becomes stale when the policy file changes, so single requests are answered
  // with the API's documented 409 RECOMMENDATION_STALE; every other request reaches the real API.
  test.setTimeout(90_000);
  const stale = {
    status: 409,
    json: {
      error: {
        code: "RECOMMENDATION_STALE",
        message:
          "Условия продуктов изменились. Пересчитайте оценку и выберите продукт заново.",
      },
    },
  };
  await registerClient(page, "app");
  await onboard(page, "Сильный бизнес");
  await openRecommendations(page);
  await page.route(
    "**/api/v1/applications",
    (route) =>
      route.request().method() === "POST"
        ? route.fulfill(stale)
        : route.continue(),
    { times: 1 },
  );
  await page
    .locator(termCard)
    .getByRole("button", { name: "Начать анкету" })
    .click();
  await expect(page.locator(termCard).getByRole("alert")).toContainText(
    "Условия продуктов изменились",
  );
  const before = await page.locator(".snapshot-note").innerText();
  await page
    .locator(termCard)
    .getByRole("button", { name: "Пересчитать оценку" })
    .click();
  await expect(page.locator(".snapshot-note")).not.toHaveText(before);
  const id = await startDraft(page, termCard);

  await completeQuestionnaire(page);
  await page.route(
    `**/api/v1/applications/${id}/submit`,
    (route) => route.fulfill(stale),
    { times: 1 },
  );
  await acceptAndSubmit(page);
  await expect(page.getByRole("alert")).toContainText(
    "Условия продуктов изменились",
  );
  await expect(page.locator(".review")).toContainText(
    "Демо-город, ул. Синтетическая, 1",
  );
  await page.getByRole("button", { name: "Пересчитать оценку" }).click();
  await expect(
    page.getByRole("heading", { name: "Найдём подходящий маршрут" }),
  ).toBeVisible();
  const { application } = await (
    await page.request.get(`/api/v1/applications/${id}`)
  ).json();
  expect(application.status).toBe("DRAFT");
});

for (const viewport of [
  { width: 390, height: 844, name: "mobile" },
  { width: 1366, height: 768, name: "laptop" },
]) {
  test(`${viewport.name} ${viewport.width}×${viewport.height}: wizard, review and status fit without horizontal scrolling and keep 44px targets`, async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await registerClient(page, "app");
    await onboard(page, "Сильный бизнес");
    await openRecommendations(page);
    const id = await startDraft(page, termCard);
    await page.setViewportSize(viewport);
    await expectStage(page, 1, "Компания");
    await expectNoPageOverflow(page);
    await expectTouchTargets(page);
    await completeQuestionnaire(page, async () => {
      await expectNoPageOverflow(page);
      await expectTouchTargets(page);
      if (
        viewport.name === "mobile" &&
        (await page.getByText("Шаг 3 из 6", { exact: true }).count())
      ) {
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({
          path: `${artifacts}/task-4b-wizard-mobile.png`,
          fullPage: true,
        });
      }
    });
    await expectNoPageOverflow(page);
    await expectTouchTargets(page);
    if (viewport.name === "mobile") {
      await page.setViewportSize({ width: 360, height: 780 });
      await expectNoPageOverflow(page);
      await page.setViewportSize(viewport);
    }
    await acceptAndSubmit(page);
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: "Заявка предварительно одобрена",
      }),
    ).toBeVisible();
    await expectNoPageOverflow(page);
    await expectTouchTargets(page);
    // Captured before any resize: a full-page capture right after a resize can repeat the first screen.
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({
      path: `${artifacts}/task-4b-status-${viewport.name}.png`,
      fullPage: true,
    });
    if (viewport.name === "mobile") {
      await page.setViewportSize({ width: 360, height: 780 });
      await expectNoPageOverflow(page);
    }
    expect((await history(page, id)).at(-1)?.to_status).toBe("PREAPPROVED");
  });
}
