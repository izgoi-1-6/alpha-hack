import { test, expect, Browser, Page } from "@playwright/test";

// Fresh synthetic clients onboard their own fixture companies; officer@demo.local is the only seeded officer and the
// queue also holds other tests' applications, so rows are always located by the application id.
const artifacts = "../.superpowers/sdd/2026-10-24-credit-route";
const termCard = '[data-product-id="alfa_term_loan_unsecured"]';
const lineCard = '[data-product-id="alfa_revolving_line_unsecured"]';
const password = "DemoCredit2026!";

async function registerClient(page: Page) {
  const email = `officer-flow-${Date.now()}-${Math.random().toString(36).slice(2)}@example.test`;
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

async function loginOfficer(page: Page) {
  await page.getByRole("button", { name: "Специалист", exact: true }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Очередь заявок" }),
  ).toBeVisible();
}

/** The officer works in a browser context of their own, beside the client's. */
async function officerPage(browser: Browser) {
  const context = await browser.newContext({
    baseURL: test.info().project.use.baseURL,
    viewport: { width: 1440, height: 1000 },
  });
  const page = await context.newPage();
  await page.goto("/");
  await loginOfficer(page);
  return page;
}

async function onboard(page: Page, fixtureText: string) {
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
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await expect(page.locator(termCard)).toBeVisible();
}

async function expectStage(page: Page, number: number, title: string) {
  await expect(
    page.getByText(`Шаг ${number} из 6`, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { level: 2, name: title, exact: true }),
  ).toBeVisible();
}

const saveAndContinue = (page: Page) =>
  page.getByRole("button", { name: "Сохранить и продолжить" }).click();

/** Completes and submits a questionnaire from a product card; the check sends it to an officer. */
async function submitForReview(
  page: Page,
  card: string,
  profile: { amount?: string; revenue?: [string, string]; debt: string },
  outcome = "Заявка на рассмотрении у специалиста",
) {
  await page
    .locator(card)
    .getByRole("button", { name: "Начать анкету" })
    .click();
  await expectStage(page, 1, "Компания");
  const id = new URL(page.url()).searchParams.get("application")!;
  expect(id).toMatch(/^[0-9a-f-]{36}$/);
  await page.getByLabel("Сведения о компании из демо-реестра верны").check();
  await page
    .getByLabel("Фактический адрес")
    .fill("Демо-город, ул. Синтетическая, 1");
  await page
    .getByLabel("Фактическая деятельность")
    .fill("Оптовая торговля (демо)");
  await saveAndContinue(page);
  await expectStage(page, 2, "Параметры");
  if (profile.amount) await page.getByLabel("Сумма, ₽").fill(profile.amount);
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
  await page
    .getByRole("group", { name: "Налоговый режим" })
    .getByLabel("УСН")
    .check();
  await page.getByLabel("Число сотрудников").fill("7");
  await page
    .getByRole("group", { name: "Выручка зависит от сезона" })
    .getByLabel("Нет")
    .check();
  await saveAndContinue(page);
  await expectStage(page, 4, "Обязательства");
  await page
    .getByLabel("Ежемесячные платежи по действующим кредитам и лизингу, ₽")
    .fill(profile.debt);
  await page.getByLabel("Налоговая задолженность, ₽").fill("0");
  await page
    .getByRole("group", { name: "Есть судебные разбирательства" })
    .getByLabel("Нет")
    .check();
  await saveAndContinue(page);
  await expectStage(page, 5, "Руководитель и владельцы");
  await page
    .getByLabel("ФИО представителя (синтетические данные)")
    .fill("Демо Представитель");
  await page.getByLabel("Подтверждаю полномочия представителя").check();
  await page.getByLabel("Сведения о владельцах указаны верно").check();
  await saveAndContinue(page);
  await expectStage(page, 6, "Проверка и согласия");
  await page.getByLabel("Подтверждаю, что сведения анкеты верны").check();
  await page.getByRole("checkbox", { name: /рассмотрения заявки/ }).check();
  await page.getByRole("checkbox", { name: /запрос кредитной истории/ }).check();
  await page.getByRole("button", { name: "Отправить заявку" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: outcome }),
  ).toBeVisible();
  return id;
}

/** Lets layout and painting catch up after a viewport change, so a capture never shows a half-resized frame. */
const settle = (page: Page) =>
  page.evaluate(
    () =>
      new Promise((done) =>
        requestAnimationFrame(() => requestAnimationFrame(done)),
      ),
  );

async function staffDetail(page: Page, id: string) {
  const response = await page.request.get(`/api/v1/officer/applications/${id}`);
  expect(response.status()).toBe(200);
  return response.json();
}

/** No page-level horizontal scroll; a dense table may scroll inside its own container. */
async function expectNoPageOverflow(page: Page) {
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

async function expectTouchTargets(page: Page) {
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

const statusPill = (page: Page) => page.locator(".review-heading .status-pill");
const decisionPanel = (page: Page) =>
  page.getByRole("region", { name: "Решение по заявке" });

test("the shell is role-aware: a client never sees officer destinations or data, an officer lands on the queue, and switching accounts leaves nothing stale", async ({
  page,
}) => {
  test.setTimeout(60_000);
  const officerCalls: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/v1/officer")) officerCalls.push(request.url());
  });
  const email = await registerClient(page);
  const nav = page.locator(".sidebar nav");
  await expect(nav.getByRole("button", { name: /Мои заявки/ })).toBeVisible();
  await expect(nav.getByRole("button", { name: "Очередь заявок" })).toHaveCount(0);

  // A client opening the officer queue address gets a clear refusal and no staff data.
  await page.goto("/?view=queue&assignee=me");
  await expect(
    page.getByRole("heading", { level: 1, name: "Нет доступа" }),
  ).toBeVisible();
  await expect(page.locator("main table")).toHaveCount(0);
  expect(officerCalls).toEqual([]);
  expect(
    (await page.request.get("/api/v1/officer/applications")).status(),
  ).toBe(403);
  await page.getByRole("button", { name: "Перейти к моим заявкам" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Мои заявки" }),
  ).toBeVisible();

  // Logging out and in as the officer shows officer navigation only, starting at the queue.
  await page.getByRole("button", { name: "Выйти из аккаунта" }).click();
  await loginOfficer(page);
  await expect(nav.getByRole("button")).toHaveText(["Очередь заявок"]);
  await expect(page.locator(".account-email")).toHaveText("officer@demo.local");
  await expect(page.locator("main")).not.toContainText("Мои компании");
  await expect(page.locator("main")).not.toContainText(email);
  // An officer opening a client destination is refused too and pointed back to the queue.
  await page.goto("/?view=applications");
  await expect(
    page.getByRole("heading", { level: 1, name: "Нет доступа" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Перейти к очереди заявок" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Очередь заявок" }),
  ).toBeVisible();
  await expect(page.locator("main table")).toBeVisible();

  // Back to the same client: no officer navigation, no queue, the client's own workspace.
  await page.getByRole("button", { name: "Выйти из аккаунта" }).click();
  const callsBefore = officerCalls.length;
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти в кабинет" }).click();
  await expect(
    page.getByRole("heading", { name: "Здесь появятся ваши компании" }),
  ).toBeVisible();
  await expect(nav.getByRole("button", { name: "Очередь заявок" })).toHaveCount(0);
  await expect(page.locator(".account-email")).toHaveText(email);
  expect(officerCalls.length).toBe(callsBefore);
});

test("A06 medium review: claim → information request → the client answers on the same application → back to the same officer → a bounded preliminary approval the client sees with distinct amounts", async ({
  page,
  browser,
}) => {
  test.setTimeout(180_000);
  await registerClient(page);
  await onboard(page, "Средний риск");
  // Medium profile: 18 months, flat 600 000 ₽ turnover, 240 000 ₽ monthly debt, clean history — 65 points.
  const id = await submitForReview(page, lineCard, {
    amount: "700000",
    debt: "240000",
  });

  const officer = await officerPage(browser);
  const row = officer.locator(`tr[data-application-id="${id}"]`);
  await expect(row).toContainText("ИП «Демо Средний риск»");
  await expect(row).toContainText("На рассмотрении");
  await expect(row.locator(".queue-assignee")).toHaveText("Не назначена");
  await expect(row).toContainText("Средний · 65");
  await expect(row).toContainText("700 000 ₽");
  await expect(row).toContainText("600 000 ₽");
  await row.scrollIntoViewIfNeeded();
  await officer.screenshot({ path: `${artifacts}/task-5b-queue-row.png` });
  await row.getByRole("link").click();
  await expect(
    officer.getByRole("heading", { level: 1, name: "ИП «Демо Средний риск»" }),
  ).toBeVisible();
  expect(new URL(officer.url()).searchParams.get("application")).toBe(id);

  // Evidence: score with each factor, labelled demo sources, amounts and the allowed range.
  const score = officer.getByRole("region", { name: "Скоринг и факторы" });
  await expect(score).toContainText("65 баллов из 100");
  await expect(score).toContainText("Средний риск");
  await expect(score).toContainText("R11");
  for (const [factor, points] of [
    ["Возраст бизнеса", "10 из 20"],
    ["Динамика выручки", "15 из 25"],
    ["Долговая нагрузка", "15 из 30"],
    ["Кредитная история", "25 из 25"],
  ])
    await expect(score.getByRole("row", { name: new RegExp(factor) })).toContainText(points);
  const sources = officer.getByRole("region", { name: "Демо-источники" });
  for (const source of ["Реестр", "Обороты", "БКИ"])
    await expect(sources).toContainText(source);
  await expect(sources.getByText("Демо · имитация")).toHaveCount(3);
  await expect(officer.getByRole("group", { name: "Запрошенная сумма" })).toContainText("700 000 ₽");
  await expect(officer.getByRole("group", { name: "Расчётный лимит" })).toContainText("600 000 ₽");
  await expect(officer.getByRole("group", { name: "Разница с лимитом" })).toContainText("+100 000 ₽");
  const range = officer.getByRole("group", { name: "Допустимая сумма одобрения" });
  await expect(range).toContainText("до 600 000 ₽");
  await expect(range).toContainText("от 300 000 ₽");
  await expect(
    officer.getByRole("region", { name: "Анкета и данные источника" }),
  ).toContainText("Совпадает с источником");

  // Only the server's allowed actions: an unassigned case offers the claim and nothing else.
  const decision = decisionPanel(officer);
  await expect(decision).toContainText("Ответственный: не назначен");
  await expect(decision.getByRole("button", { name: "Предварительно одобрить" })).toHaveCount(0);
  await decision.getByRole("button", { name: "Взять в работу" }).click();
  await expect(decision).toContainText("Ответственный: Я");
  await expect(officer.locator(".officer-live")).toContainText("Заявка взята в работу");
  await expect(decision.getByLabel("Сумма предварительного одобрения, ₽")).toHaveValue("600000");
  await expect(decision).toContainText("Предварительное одобрение — не окончательное решение");
  await officer.evaluate(() => window.scrollTo(0, 0));
  await officer.screenshot({
    path: `${artifacts}/task-5b-review-desktop.png`,
    fullPage: true,
  });
  await decision.screenshot({ path: `${artifacts}/task-5b-decision-controls.png` });

  // A second tab of the same officer asks the client about the debt payments.
  const second = await officer.context().newPage();
  await second.goto(`/?application=${id}`);
  const secondDecision = decisionPanel(second);
  await secondDecision.getByRole("button", { name: "Запрос сведений" }).click();
  // The stage-2 need is fixed after submission and is never offered.
  await expect(secondDecision.getByLabel("Сумма, ₽", { exact: true })).toHaveCount(0);
  await secondDecision
    .getByLabel("Ежемесячные платежи по действующим кредитам и лизингу, ₽")
    .check();
  const question = "Уточните ежемесячные платежи по кредитам и лизингу на сегодня.";
  await secondDecision.getByLabel("Вопрос клиенту").fill(question);
  await secondDecision.getByRole("button", { name: "Отправить запрос" }).click();
  await expect(statusPill(second)).toHaveText("Нужны сведения");
  await expect(
    second.getByRole("region", { name: "Запросы сведений" }),
  ).toContainText("Открыт");
  await second.close();

  // The client sees the question and answers exactly the requested field.
  await page.reload();
  await expect(
    page.getByRole("heading", { level: 1, name: "Нужны дополнительные сведения" }),
  ).toBeVisible();
  await expect(page.locator(".info-request")).toContainText(question);
  const form = page.getByRole("form", { name: "Ответ на запрос" });
  const debt = form.getByLabel(
    "Ежемесячные платежи по действующим кредитам и лизингу, ₽",
  );
  await expect(debt).toHaveValue("240000");
  await expect(form.getByRole("textbox")).toHaveCount(2);
  await debt.fill("200000");
  const answer = "Платежи снизились после досрочного погашения лизинга (демо).";
  await form.getByLabel("Ответ специалисту").fill(answer);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: `${artifacts}/task-5b-respond-info.png`,
    fullPage: true,
  });
  await form.getByRole("button", { name: "Отправить ответ" }).click();
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Заявка на рассмотрении у специалиста",
    }),
  ).toBeVisible();
  await expect(page.getByRole("form", { name: "Ответ на запрос" })).toHaveCount(0);
  await expect(page.getByRole("list", { name: "История заявки" })).toContainText(answer);

  // The first officer tab is now outdated: its decision meets the version conflict, reloads and keeps the reason.
  const reason = "Средний риск: одобряем в пределах расчётного лимита (демо).";
  await decision.getByLabel("Основание решения").fill(reason);
  await decision.getByRole("button", { name: "Предварительно одобрить" }).click();
  await expect(decision.getByRole("alert")).toContainText("Заявка изменилась");
  await expect(decision.getByLabel("Основание решения")).toHaveValue(reason);
  await expect(statusPill(officer)).toHaveText("На рассмотрении");
  await expect(decision).toContainText("Ответственный: Я");
  const requests = officer.getByRole("region", { name: "Запросы сведений" });
  await expect(requests).toContainText(answer);
  await expect(requests).toContainText("Закрыт");
  await expect(
    officer.getByRole("region", { name: "Проверки по заявке" }).locator(".evaluation-list > li"),
  ).toHaveCount(2);

  // An amount above min(request, scored limit) is refused by the server, its message next to the amount.
  const amount = decision.getByLabel("Сумма предварительного одобрения, ₽");
  await amount.fill("600001");
  await decision.getByRole("button", { name: "Предварительно одобрить" }).click();
  await expect(decision.getByRole("alert")).toContainText("от 300 000 ₽ до 600 000 ₽");
  await expect(decision.locator("#preapprove-amount-error")).toContainText("до 600 000 ₽");
  await expect(statusPill(officer)).toHaveText("На рассмотрении");

  // A lost response: the repeat reuses the idempotency key and the server replays one decision.
  const keys: string[] = [];
  await officer.route(
    /\/api\/v1\/officer\/applications\/[^/]+\/preapprove$/,
    async (route) => {
      keys.push(route.request().headers()["idempotency-key"]);
      const response = await route.fetch();
      if (keys.length === 1) await route.abort();
      else await route.fulfill({ response });
    },
  );
  await amount.fill("600000");
  await decision.getByRole("button", { name: "Предварительно одобрить" }).click();
  await expect(decision.getByRole("alert")).toContainText("Нет связи с сервером");
  await decision.getByRole("button", { name: "Предварительно одобрить" }).click();
  await expect(statusPill(officer)).toHaveText("Предварительно одобрена");
  await expect(officer.locator(".officer-live")).toContainText("600 000 ₽");
  expect(keys).toHaveLength(2);
  expect(keys[1]).toBe(keys[0]);
  const detail = await staffDetail(officer, id);
  expect(detail.decisions.map((row: { action: string }) => row.action)).toEqual([
    "request_info",
    "preapprove",
  ]);
  expect(detail.application.preapproved_amount_rub).toBe(600000);
  expect(detail.application.requested_amount_rub).toBe(700000);
  await expect(
    officer.getByRole("region", { name: "Решения специалиста" }),
  ).toContainText(reason);
  await expect(officer.getByRole("group", { name: "Предварительно одобрено" })).toContainText("600 000 ₽");
  // Only a final-phase rejection remains for the document stage.
  await expect(decision.getByRole("button", { name: "Предварительно одобрить" })).toHaveCount(0);
  await expect(decision).toContainText("Окончательный отказ");

  // The review page at phone width: no page overflow, 44px targets (no sidebar slide caught mid-way).
  await officer.emulateMedia({ reducedMotion: "reduce" });
  await officer.setViewportSize({ width: 390, height: 844 });
  await expectNoPageOverflow(officer);
  await expectTouchTargets(officer);
  await officer.evaluate(() => window.scrollTo(0, 0));
  await settle(officer);
  await officer.screenshot({
    path: `${artifacts}/task-5b-review-mobile.png`,
    fullPage: true,
  });

  // The client sees the preliminary approval with each amount labelled on its own.
  await page.reload();
  await expect(
    page.getByRole("heading", { level: 1, name: "Заявка предварительно одобрена" }),
  ).toBeVisible();
  await expect(page.getByRole("group", { name: "Запрошенная сумма" })).toContainText("700 000 ₽");
  await expect(
    page.getByRole("group", { name: "Предварительная оценка лимита" }),
  ).toContainText("1 800 000 ₽");
  const preapproved = page.getByRole("group", { name: "Предварительно одобрено" });
  await expect(preapproved).toContainText("600 000 ₽");
  await expect(preapproved).toContainText("не окончательное решение");
  await expect(page.locator(".status-next")).toContainText(reason);
  const timeline = page.getByRole("list", { name: "История заявки" });
  await expect(timeline).toContainText(reason);
  await expect(timeline).toContainText("Сотрудник банка");
});

test("filters survive a reload; a non-computable limit is refused with the server's reason; a confirmed preliminary rejection reaches the client", async ({
  page,
  browser,
}) => {
  test.setTimeout(150_000);
  await registerClient(page);
  await onboard(page, "Неполные обороты");
  // The source has no turnover: zero declared revenue routes to review with no computable score or limit.
  const id = await submitForReview(page, termCard, {
    revenue: ["0", "0"],
    debt: "0",
  });

  const officer = await officerPage(browser);
  const row = officer.locator(`tr[data-application-id="${id}"]`);
  const assignee = officer.getByRole("group", { name: "Ответственный" });
  await officer.goto("/?view=queue&assignee=unassigned");
  await expect(row.locator(".queue-assignee")).toHaveText("Не назначена");
  await officer.reload();
  await expect(assignee.getByLabel("Не назначены")).toBeChecked();
  await expect(row).toBeVisible();
  await assignee.getByLabel("Мои").check();
  await expect(officer).toHaveURL(/assignee=me/);
  await expect(officer.getByText(/^Найдено:/)).toBeVisible();
  await expect(row).toHaveCount(0);
  await officer.getByLabel("Статус").selectOption("MANUAL_REVIEW");
  await assignee.getByLabel("Не назначены").check();
  await expect(officer).toHaveURL(/status=MANUAL_REVIEW/);
  await expect(officer).toHaveURL(/assignee=unassigned/);
  await expect(row).toContainText("Не рассчитан");
  await officer.setViewportSize({ width: 1366, height: 768 });
  await expectNoPageOverflow(officer);
  await officer.evaluate(() => window.scrollTo(0, 0));
  await settle(officer);
  await officer.screenshot({ path: `${artifacts}/task-5b-queue.png` });
  await officer.setViewportSize({ width: 1440, height: 1000 });

  await row.getByRole("link").click();
  await expect(
    officer.getByRole("heading", { level: 1, name: "ИП «Демо Неполные обороты»" }),
  ).toBeVisible();
  await expect(officer.getByRole("region", { name: "Скоринг и факторы" })).toContainText(
    "Балл не рассчитан",
  );
  await expect(
    officer.getByRole("region", { name: "Анкета и данные источника" }),
  ).toContainText("Заявлено клиентом");
  await expect(
    officer.getByRole("group", { name: "Допустимая сумма одобрения" }),
  ).toContainText("Недоступно");

  // A competing claim (the seed has one officer, so the reply is injected once): reload and say who holds it.
  let claims = 0;
  let reads = 0;
  officer.on("request", (request) => {
    if (request.method() === "GET" && request.url().endsWith(`/officer/applications/${id}`)) reads += 1;
  });
  await officer.route(/\/officer\/applications\/[^/]+\/claim$/, async (route) => {
    claims += 1;
    if (claims > 1) return route.continue();
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "ALREADY_ASSIGNED",
          message: "Заявку уже взял в работу другой специалист.",
        },
      }),
    });
  });
  const decision = decisionPanel(officer);
  await decision.getByRole("button", { name: "Взять в работу" }).click();
  await expect(decision.getByRole("alert")).toContainText(
    "Заявку уже взял в работу другой специалист.",
  );
  await expect.poll(() => reads).toBeGreaterThan(0);
  await decision.getByRole("button", { name: "Взять в работу" }).click();
  await expect(decision).toContainText("Ответственный: Я");
  // The server's refusal reason replaces the preapproval control.
  await expect(decision).toContainText("Лимит не рассчитан");
  await expect(decision.getByRole("button", { name: "Одобрение" })).toHaveCount(0);

  // Back to the remembered filters: the claimed case left «Не назначены» and is under «Мои» after a reload.
  await officer.getByRole("button", { name: "← Очередь заявок" }).click();
  await expect(officer).toHaveURL(/assignee=unassigned/);
  await expect(officer.getByText(/^Найдено:/)).toBeVisible();
  await expect(row).toHaveCount(0);
  await assignee.getByLabel("Мои").check();
  await expect(row.locator(".queue-assignee")).toHaveText("Я");
  await officer.reload();
  await expect(assignee.getByLabel("Мои")).toBeChecked();
  await expect(officer.getByLabel("Статус")).toHaveValue("MANUAL_REVIEW");
  await expect(row).toBeVisible();

  // A preliminary rejection: the phase is shown and the reason is confirmed before sending.
  await row.getByRole("link").click();
  await decision.getByRole("button", { name: "Отказ", exact: true }).click();
  await expect(decision).toContainText("Предварительный отказ");
  const reason = "Выручка не подтверждена источником, лимит рассчитать нельзя (демо).";
  await decision.getByLabel("Причина отказа").fill(reason);
  await decision.getByRole("button", { name: "Отказать", exact: true }).click();
  await expect(decision.getByRole("group", { name: "Отказать по заявке?" })).toBeVisible();
  await decision.getByRole("button", { name: "Да, отказать" }).click();
  await expect(statusPill(officer)).toHaveText("Отказ");
  await expect(
    officer.getByRole("region", { name: "Решения специалиста" }),
  ).toContainText("Отказ · предварительный");
  await expect(decision.getByRole("button")).toHaveCount(0);
  const detail = await staffDetail(officer, id);
  expect(detail.decisions).toHaveLength(1);
  expect(detail.decisions[0]).toMatchObject({ action: "reject", phase: "preliminary", reason });

  // The client sees the rejection and the officer's reason.
  await page.reload();
  await expect(
    page.getByRole("heading", { level: 1, name: "По заявке отказ" }),
  ).toBeVisible();
  await expect(page.locator(".status-next")).toContainText(reason);
  await expect(page.getByRole("list", { name: "История заявки" })).toContainText(reason);
});

test("a trusted-source request keeps the retry path and never shows the answer form; once the application is cancelled its unresolved request is an audit row with nothing to act on", async ({
  page,
  browser,
}) => {
  test.setTimeout(120_000);
  await registerClient(page);
  await onboard(page, "БКИ без категории");
  // The demo BKI answers without the history category: a system request that only a retry of the source can close.
  const id = await submitForReview(
    page,
    termCard,
    { debt: "160000" },
    "Нужны дополнительные сведения",
  );
  await expect(page.locator(".info-request")).toContainText("Запрос системы");
  await expect(page.getByRole("button", { name: "Повторить проверку" })).toBeVisible();
  await expect(page.getByRole("form", { name: "Ответ на запрос" })).toHaveCount(0);
  await page.getByRole("button", { name: "Отменить заявку" }).click();
  await page.getByLabel("Причина отмены").fill("Проверка записи о запросе (демо)");
  await page.getByRole("button", { name: "Да, отменить заявку" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Заявка отменена" }),
  ).toBeVisible();

  const officer = await officerPage(browser);
  await officer.goto(`/?application=${id}`);
  await expect(statusPill(officer)).toHaveText("Отменена");
  const requests = officer.getByRole("region", { name: "Запросы сведений" });
  await expect(requests).toContainText("Повторный запрос к демо-источнику: БКИ");
  await expect(requests).toContainText("Не завершён: заявка закрыта");
  await expect(requests).not.toContainText("Открыт");
  await expect(decisionPanel(officer)).toContainText("Заявка закрыта");
  await expect(decisionPanel(officer).getByRole("button")).toHaveCount(0);
});
