import { expect, Page } from "@playwright/test";
import { test } from "./fixtures";
import {
  decisionPanel,
  expectNoDemoWording,
  expectNoPageOverflow,
  expectTouchTargets,
  history,
  lineCard,
  officerPage,
  onboard,
  registerClient,
  revision,
  settle,
  staffDetail,
  statusPill,
  submitApplication,
  termCard,
} from "./helpers";

// End-to-end journeys against the real app (Task 13): fresh synthetic clients, officer@demo.local in a browser
// context of its own, no injected replies.

const shot = (page: Page, name: string) =>
  page.screenshot({ path: `${revision}/task-13-${name}.png`, fullPage: true });
const heading = (page: Page, name: string) =>
  page.getByRole("heading", { level: 1, name });

test("journey 2 — a medium-risk application: the officer asks for the debt payments, the client answers on the same application, and the officer preliminarily approves within the scored limit", async ({
  page,
  browser,
}) => {
  test.setTimeout(240_000);
  await registerClient(page, "journey-review");
  await onboard(page, "Средний риск");
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  // 700 000 ₽ on the revolving line: within its estimate (3 × 600 000 ₽), above the medium-risk scored limit.
  await page.getByLabel("Сумма, ₽", { exact: true }).fill("700000");
  await expect(page.locator(lineCard)).toContainText("Расчёт на сумму 700 000 ₽");
  const id = await submitApplication(
    page,
    lineCard,
    { debt: "240000", term: null },
    "Заявка на рассмотрении у специалиста",
  );
  // MANUAL_REVIEW as the client sees it: no decision yet, the turnover estimate, and no score or scored limit.
  await expect(page.locator(".status-pill")).toHaveText("На рассмотрении");
  await expect(page.locator(".status-next")).toContainText("Пока это не одобрение");
  await expect(page.getByRole("group", { name: "Запрошенная сумма" })).toContainText("700 000 ₽");
  await expect(
    page.getByRole("group", { name: "Предварительная оценка лимита" }),
  ).toContainText("1 800 000 ₽");
  await expect(page.getByRole("group", { name: "Предварительно одобрено" })).toHaveCount(0);
  await expect(page.locator(".status-result")).toContainText("Заявку рассмотрит кредитный специалист.");
  await expect(page.locator(".status-result")).not.toContainText(/балл|риск|скоринг|лимит|600 000/i);
  await expectNoDemoWording(page);
  await shot(page, "journey-manual-review");

  // The officer finds the case in the queue, claims it and asks the client about the debt payments.
  const officer = await officerPage(browser);
  const row = officer.locator(`tr[data-application-id="${id}"]`);
  await expect(row).toContainText("ИП «Средний риск»");
  await expect(row).toContainText("Средний · 65");
  await row.getByRole("link").click();
  const decision = decisionPanel(officer);
  await decision.getByRole("button", { name: "Взять в работу" }).click();
  await expect(decision).toContainText("Ответственный: Я");
  await decision.getByRole("button", { name: "Запрос сведений" }).click();
  await decision
    .getByLabel("Ежемесячные платежи по действующим кредитам и лизингу, ₽")
    .check();
  const question = "Уточните ежемесячные платежи по кредитам и лизингу на сегодня.";
  await decision.getByLabel("Вопрос клиенту").fill(question);
  await decision.getByRole("button", { name: "Отправить запрос" }).click();
  await expect(statusPill(officer)).toHaveText("Нужны сведения");

  // NEED_INFO as the client sees it: the question and a form for exactly the requested answer.
  await page.reload();
  await expect(heading(page, "Нужны дополнительные сведения")).toBeVisible();
  await expect(page.locator(".status-pill")).toHaveText("Нужны сведения");
  await expect(page.locator(".info-request")).toContainText(question);
  const form = page.getByRole("form", { name: "Ответ на запрос" });
  const debt = form.getByLabel("Ежемесячные платежи по действующим кредитам и лизингу, ₽");
  await expect(debt).toHaveValue("240000");
  await debt.fill("200000");
  const answer = "Платежи снизились после досрочного погашения лизинга.";
  await form.getByLabel("Ответ специалисту").fill(answer);
  await expectNoDemoWording(page);
  await shot(page, "journey-need-info");
  await form.getByRole("button", { name: "Отправить ответ" }).click();
  await expect(heading(page, "Заявка на рассмотрении у специалиста")).toBeVisible();

  // Back to the same officer: the answer, a fresh evaluation, and the server's bounds for the decision.
  await officer.reload();
  await expect(statusPill(officer)).toHaveText("На рассмотрении");
  await expect(decision).toContainText("Ответственный: Я");
  const requests = officer.getByRole("region", { name: "Запросы сведений" });
  await expect(requests).toContainText(answer);
  await expect(requests).toContainText("Закрыт");
  const amount = decision.getByLabel("Сумма предварительного одобрения, ₽");
  await expect(amount).toHaveValue("600000");
  const reason = "Платежи по кредитам уточнены: одобряем предварительно.";
  await decision.getByLabel("Основание решения").fill(reason);
  // Above min(request, scored limit) the server refuses, with its message beside the amount.
  await amount.fill("600001");
  await decision.getByRole("button", { name: "Предварительно одобрить" }).click();
  await expect(decision.locator("#preapprove-amount-error")).toContainText("до 600 000 ₽");
  await amount.fill("600000");
  await decision.getByRole("button", { name: "Предварительно одобрить" }).click();
  await expect(statusPill(officer)).toHaveText("Предварительно одобрена");
  const detail = await staffDetail(officer, id);
  expect(detail.decisions.map((entry: { action: string }) => entry.action)).toEqual([
    "request_info",
    "preapprove",
  ]);
  expect(detail.application).toMatchObject({
    requested_amount_rub: 700000,
    preapproved_amount_rub: 600000,
    scored_limit_rub: 600000,
  });

  // The client: three different amounts, the officer's reason, the whole path in the history.
  await page.reload();
  await expect(heading(page, "Заявка предварительно одобрена")).toBeVisible();
  await expect(page.getByRole("group", { name: "Запрошенная сумма" })).toContainText("700 000 ₽");
  await expect(page.getByRole("group", { name: "Предварительно одобрено" })).toContainText("600 000 ₽");
  await expect(page.locator(".status-next")).toContainText(reason);
  expect((await history(page, id)).map((item) => item.reason_code)).toEqual([
    "CREATED",
    "SUBMITTED",
    "CHECK_RESULT",
    "INFO_REQUESTED",
    "INFO_PROVIDED",
    "R12",
  ]);
});

test("journey 4 — missing data and a source outage: undeclared turnover is declared in the questionnaire and reviewed; an unavailable registry recovers on retry before applying", async ({
  page,
  browser,
}) => {
  test.setTimeout(240_000);
  await registerClient(page, "journey-recovery");

  // Turnover unknown to the sources: no estimate, but a questionnaire where the client declares it.
  await onboard(page, "Неполные обороты");
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await expect(page.getByText("Нет положительных сведений об обороте")).toBeVisible();
  await expect(
    page.locator(termCard).getByRole("group", { name: "Личная предварительная оценка" }),
  ).toContainText("Нужно уточнить");
  await page.getByLabel("Сумма, ₽", { exact: true }).fill("1000000");
  await expect(page.locator(termCard)).toContainText("Оборот неизвестен");
  const declared = await submitApplication(
    page,
    termCard,
    { debt: "160000", revenue: ["700000", "650000"] },
    "Заявка на рассмотрении у специалиста",
  );
  // A declared turnover is checked by a specialist (R5) rather than scored as if it came from a source.
  await expect(page.locator(".status-result")).toContainText("кредитный специалист");
  const officer = await officerPage(browser);
  await officer.goto(`/?application=${declared}`);
  await expect(
    officer.getByRole("region", { name: "Анкета и данные источника" }),
  ).toContainText("Заявлено клиентом");
  expect((await staffDetail(officer, declared)).application.latest_evaluation.rule).toBe("R5");

  // The registry did not answer: eligibility is unknown and no application can start until a retry.
  await onboard(page, "Реестр недоступен");
  await expect(page.locator("main")).toContainText("Реестр временно недоступен");
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await expect(page.getByText("Статус компании в реестре не подтверждён")).toBeVisible();
  await expect(page.locator(termCard)).toContainText("Нужны сведения");
  await expect(page.getByRole("button", { name: "Начать анкету" })).toHaveCount(0);
  await page.getByRole("button", { name: "Профиль компании" }).click();
  await page.getByRole("button", { name: "Повторить проверку" }).click();
  await expect(page.getByText("Действующая компания", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await expect(page.locator(termCard)).toContainText("Соответствует потребности");
  await page.getByLabel("Сумма, ₽", { exact: true }).fill("1000000");
  await expect(page.locator(termCard)).toContainText("Расчёт на сумму 1 000 000 ₽");
  const recovered = await submitApplication(
    page,
    termCard,
    { debt: "160000" },
    "Заявка предварительно одобрена",
  );
  await expect(page.getByRole("group", { name: "Предварительно одобрено" })).toContainText(
    "1 000 000 ₽",
  );
  expect((await history(page, recovered)).map((item) => item.reason_code)).toEqual([
    "CREATED",
    "SUBMITTED",
    "CHECK_RESULT",
  ]);

  // Both applications in «Мои заявки» on a 390 px phone: each with its status and next step, nothing overflows.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?view=applications");
  await expect(heading(page, "Мои заявки")).toBeVisible();
  const rows = page.locator(".application-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.filter({ hasText: "ИП «Неполные обороты»" })).toContainText("На рассмотрении");
  await expect(rows.filter({ hasText: "ООО «Реестр недоступен»" })).toContainText(
    "Предварительно одобрена",
  );
  await settle(page);
  await expectNoPageOverflow(page);
  await expectTouchTargets(page);
  await expectNoDemoWording(page);
  await shot(page, "journey-my-applications-390");
});
