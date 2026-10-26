import { expect, Page } from "@playwright/test";
import { test } from "./fixtures";
import {
  acceptAndSubmit,
  authorityDialog,
  decisionPanel,
  documentsCard,
  expectNoDemoWording,
  expectNoPageOverflow,
  expectStage,
  expectTouchTargets,
  fillCompanyStage,
  fillFinanceStage,
  fillObligationsStage,
  fillParametersStage,
  fillRepresentativeStage,
  history,
  logOut,
  officerPage,
  onboard,
  registerClient,
  requirementRow,
  artifacts,
  reviewDocument,
  saveAndContinue,
  settle,
  signIn,
  staffDetail,
  statusPill,
  submitApplication,
  uploadDocument,
} from "./helpers";
import { pdfFile, pngFile } from "./files";

// End-to-end journeys against the real app: fresh synthetic clients, officer@demo.local in a browser
// context of its own, no injected replies. The journey of a brand-new client follows the walkthrough (switched on
// here) up to the questionnaire and goes on to the final approval and the Alfa-Business hand-off.

const walkthrough = (page: Page) =>
  page.getByRole("dialog", { name: /^Шаг \d+ из 9/ });
const tourButton = (page: Page, name: string) =>
  walkthrough(page).getByRole("button", { name, exact: true });
const expectStep = (page: Page, number: number) =>
  expect(walkthrough(page)).toHaveAccessibleName(
    new RegExp(`^Шаг ${number} из 9(\\s|$)`),
  );
const shot = (page: Page, name: string, fullPage = true) =>
  page.screenshot({ path: `${artifacts}/${name}.png`, fullPage });

/** No page overflow and 44 px targets at a laptop and a phone size; captures each. */
async function checkSizes(page: Page, name: string) {
  // The phone sidebar slides for 0.2 s after a resize; reduced motion keeps the captures still.
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const [width, height, size] of [
    [1366, 768, "1366"],
    [390, 844, "390"],
  ] as const) {
    await page.setViewportSize({ width, height });
    await settle(page);
    await expectNoPageOverflow(page);
    await expectTouchTargets(page);
    await page.evaluate(() => window.scrollTo(0, 0));
    await settle(page);
    await shot(page, `${name}-${size}`);
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await settle(page);
}

test.describe("a brand-new client with the walkthrough on", () => {
  test.use({ tour: true });

  test("journey 1 — walkthrough → onboarding with Госуслуги → product choice → questionnaire → preliminary approval → documents → final approval → the Alfa-Business hand-off", async ({
    page,
    browser,
  }) => {
    test.setTimeout(300_000);
    await page.emulateMedia({ reducedMotion: "reduce" });
    const email = await registerClient(page, "journey-approval");

    // The walkthrough opens by itself and leads the client through the real pages.
    await expectStep(page, 1);
    await expect(walkthrough(page)).toContainText("Начните с компании");
    await page.locator('[data-tour="add-company"]').click();
    await expectStep(page, 2);
    await page.getByRole("button").filter({ hasText: "Сильный бизнес" }).click();
    await tourButton(page, "Далее").click();
    await expectStep(page, 3);
    await page
      .getByRole("button", { name: "Подтвердить через Госуслуги" })
      .click();
    const dialog = authorityDialog(page);
    await expect(dialog).toContainText("Соколов Андрей Викторович");
    await expect(dialog).toContainText("Генеральный директор");
    await dialog.getByRole("button", { name: "Подтвердить" }).click();
    await expect(dialog).toHaveCount(0);
    await expectStep(page, 3);
    await tourButton(page, "Далее").click();
    await expectStep(page, 4);
    for (const checkbox of await page
      .locator("#onboarding-consents")
      .getByRole("checkbox")
      .all())
      await checkbox.check();
    await page.getByRole("button", { name: "Добавить и проверить" }).click();
    await expect(
      page.getByRole("heading", { name: "Что удалось узнать" }),
    ).toBeVisible();
    await expectStep(page, 5);
    await page.getByRole("button", { name: "Подобрать финансирование" }).click();
    await expectStep(page, 6);
    await tourButton(page, "Далее").click();
    await expectStep(page, 7);
    await expect(walkthrough(page)).toContainText("не означает одобрения");
    await tourButton(page, "Далее").click();
    await expectStep(page, 8);
    // The highlighted «Начать анкету» is the first card's, the best-ranked one: the unsecured term loan.
    const first = page.locator("article[data-product-id]").first();
    await expect(first).toHaveAttribute("data-product-id", "alfa_term_loan_unsecured");
    await expect(page.locator('[data-tour="start-application"]').first()).toHaveAccessibleDescription(
      "Кредит одной суммой без залога",
    );
    await first.locator('[data-tour="start-application"]').click();
    await expectStage(page, 1, "Компания");
    await expectStep(page, 9);
    await expectNoDemoWording(page);
    await tourButton(page, "Готово").click();
    await expect(walkthrough(page)).toHaveCount(0);
    const id = new URL(page.url()).searchParams.get("application")!;

    // The questionnaire: the amount came from the product screen; the sources' answers are read-only.
    await fillCompanyStage(page);
    await saveAndContinue(page);
    await expectStage(page, 2, "Параметры");
    await expect(page.getByLabel("Сумма, ₽")).toHaveValue("2000000");
    await fillParametersStage(page);
    await saveAndContinue(page);
    await expectStage(page, 3, "Бизнес и финансы");
    await fillFinanceStage(page);
    await saveAndContinue(page);
    await expectStage(page, 4, "Обязательства");
    await fillObligationsStage(page, "160000");
    await saveAndContinue(page);
    await expectStage(page, 5, "Руководитель и владельцы");
    await fillRepresentativeStage(page);
    await saveAndContinue(page);
    await expectStage(page, 6, "Проверка и согласия");
    await acceptAndSubmit(page);
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: "Заявка предварительно одобрена",
      }),
    ).toBeVisible();
    // Low risk, 100 points, scored limit 3 × 800 000 ₽: R8 for the 2 000 000 ₽ asked. The client sees none of it.
    await expect(page.locator(".status-result")).toContainText(
      "Заявка предварительно одобрена. Это не окончательное решение.",
    );
    await expect(page.locator(".status-result")).not.toContainText(/балл|риск|скоринг|лимит/i);
    await expect(
      page.getByRole("group", { name: "Предварительно одобрено" }),
    ).toContainText("2 000 000 ₽");
    const items = await history(page, id);
    expect(items.map((item) => [item.to_status, item.reason_code])).toEqual([
      ["DRAFT", "CREATED"],
      ["CHECKING", "SUBMITTED"],
      ["PREAPPROVED", "CHECK_RESULT"],
    ]);
    // The server writes the amount of its notice with U+00A0 between the digit groups and before the sign, so it
    // never wraps. Read from the API: the timeline joins ASCII-spaced amounts too, so it cannot tell.
    expect(items.at(-1)!.notification!.message).toContain(
      "на 2\u00a0000\u00a0000\u00a0₽",
    );

    // Documents: the two base documents, then the packet goes to the officer.
    const card = documentsCard(page);
    await uploadDocument(
      requirementRow(card, "BANK_STATEMENT"),
      pdfFile("Выписка за квартал.pdf"),
    );
    await uploadDocument(
      requirementRow(card, "FINANCIAL_REPORT"),
      pngFile("Баланс 2026.png"),
    );
    await card.getByRole("button", { name: "Отправить комплект" }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: "Документы на проверке" }),
    ).toBeVisible();

    // The officer claims the case, accepts both files and opens the final decision at the server's bound.
    const officer = await officerPage(browser);
    await officer.goto(`/?application=${id}`);
    await expect(statusPill(officer)).toHaveText("Документы на проверке");
    const decision = decisionPanel(officer);
    await decision.getByRole("button", { name: "Взять в работу" }).click();
    await expect(decision).toContainText("Ответственный: Я");
    await reviewDocument(officer, "BANK_STATEMENT", "Принять", "Обороты совпадают с анкетой.");
    await reviewDocument(officer, "FINANCIAL_REPORT", "Принять", "Отчётность за нужный период.");
    const amount = decision.getByLabel("Итоговая сумма, ₽");
    await expect(amount).toHaveValue("2000000");
    await expect(decision).toContainText("от 300 000 ₽ до 2 000 000 ₽");
    const reason = "Документы приняты, одобряем 2 000 000 ₽.";
    await decision.getByLabel("Основание решения").fill(reason);
    // The review page with the final decision open, at a laptop and a phone size.
    await checkSizes(officer, "journey-officer-final");
    // «Вернуться» from the confirmation gives focus back to the action.
    await decision.getByRole("button", { name: "Одобрить окончательно" }).click();
    await expect(decision.getByRole("button", { name: "Вернуться" })).toBeFocused();
    await decision.getByRole("button", { name: "Вернуться" }).click();
    await expect(
      decision.getByRole("button", { name: "Одобрить окончательно" }),
    ).toBeFocused();
    await decision.getByRole("button", { name: "Одобрить окончательно" }).click();
    await decision.getByRole("button", { name: "Да, одобрить" }).click();
    await expect(statusPill(officer)).toHaveText("Одобрена");
    expect((await staffDetail(officer, id)).application.final_amount_rub).toBe(2000000);
    await expectNoDemoWording(officer);

    // The client's outcome: each amount on its own tile, no money issued here.
    await page.reload();
    await expect(
      page.getByRole("heading", { level: 1, name: "Заявка одобрена" }),
    ).toBeVisible();
    await expect(page.locator(".status-next")).toContainText(reason);
    await expect(page.getByRole("group", { name: "Итоговая сумма" })).toContainText(
      "деньги не перечисляются",
    );
    await expectNoDemoWording(page);
    await checkSizes(page, "journey-approved");

    // The hand-off page, then Back and Forward through the browser history.
    await page.getByRole("button", { name: "Перейти в Альфа-Бизнес" }).click();
    await expect(page).toHaveURL(new RegExp(`/alfa-business/${id}$`));
    const handoff = page.getByRole("heading", { level: 1, name: "Переход в Альфа-Бизнес" });
    await expect(handoff).toBeVisible();
    await expect(page.locator("main")).toContainText("Деньги не перечисляются");
    await expect(page.locator("main")).toContainText("2 000 000 ₽");
    await expectNoDemoWording(page);
    await checkSizes(page, "journey-handoff");
    await page.goBack();
    await expect(
      page.getByRole("heading", { level: 1, name: "Заявка одобрена" }),
    ).toBeVisible();
    expect(new URL(page.url()).searchParams.get("application")).toBe(id);
    await page.goForward();
    await expect(handoff).toBeVisible();
    // Logging out from the hand-off page leaves no trace of it: the next sign-in starts at home.
    await logOut(page);
    expect(new URL(page.url()).pathname).toBe("/");
    await signIn(page, email);
    await expect(
      page.getByRole("heading", { name: "ООО «Сильный бизнес»" }),
    ).toBeVisible();
    expect(new URL(page.url()).pathname).toBe("/");
    // The walkthrough was completed: it does not open again.
    await settle(page);
    await expect(walkthrough(page)).toHaveCount(0);
  });
});

/** The annuity, rounded half up, in exact integer arithmetic (an oracle independent of the app). */
function annuity(amount: number, bps: number, months: number) {
  const [a, p, q] = [BigInt(amount), BigInt(bps), 120_000n];
  const grown = (q + p) ** BigInt(months);
  const numerator = a * p * grown;
  const denominator = q * (grown - q ** BigInt(months));
  return Number((2n * numerator + denominator) / (2n * denominator));
}

test("journey 7 — a manufacturer in a border region applies for the border-territories gov program and is preliminarily approved for 20 000 000 ₽", async ({
  page,
  browser,
}) => {
  test.setTimeout(180_000);
  await registerClient(page, "journey-gov");
  await onboard(page, "Курский производитель");
  await expect(page.locator("main")).toContainText("Курская область");
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await page.getByLabel("Сумма, ₽", { exact: true }).fill("20000000");
  const border = page.locator('[data-product-id="psk_borderline"]');
  await expect(border).toContainText("Расчёт на сумму 20 000 000 ₽");
  // The gov program fits: ООО, SME register, Курская область, main OKVED 25 (not denied), 3 × 12 000 000 ₽ turnover.
  await expect(border.locator(".product-status")).toHaveText("Соответствует потребности");
  await expect(border.getByText("Госпрограмма")).toBeVisible();
  // 14% for the first 12 months: the payment is labelled with the preferential period (36-month estimate term).
  await expect(border.locator(".product-payment")).toContainText(
    annuity(20000000, 1400, 36).toLocaleString("ru-RU").replace(/\s/g, " "),
  );
  await expect(border.locator(".product-payment")).toContainText("в льготный период 12 мес.");
  await border.scrollIntoViewIfNeeded();
  await border.screenshot({ path: `${artifacts}/journey-gov-card.png` });

  const id = await submitApplication(
    page,
    '[data-product-id="psk_borderline"]',
    { purpose: "Инвестиции", term: "36", debt: "2000000" },
    "Заявка предварительно одобрена",
  );
  // The scored limit is the program maximum (30 000 000 ₽, below 3 × turnover); the 20 000 000 ₽ asked is approved.
  // The client reads only the outcome; the officer below sees the score and the limit.
  await expect(page.locator(".status-result")).toContainText("Заявка предварительно одобрена.");
  await expect(page.locator(".status-result")).not.toContainText(/балл|риск|скоринг|лимит|30 000 000/i);
  await expect(
    page.getByRole("group", { name: "Предварительно одобрено" }),
  ).toContainText("20 000 000 ₽");
  const card = documentsCard(page);
  await expect(requirementRow(card, "BANK_STATEMENT")).toBeVisible();
  await expect(requirementRow(card, "FINANCIAL_REPORT")).toBeVisible();
  await expect(card.locator("[data-document-type]")).toHaveCount(2);
  await shot(page, "journey-gov-preapproved");

  // The officer sees the pinned gov program, unsecured with the two base documents.
  const officer = await officerPage(browser);
  const detail = await staffDetail(officer, id);
  expect(detail.application).toMatchObject({
    product_id: "psk_borderline",
    status: "PREAPPROVED",
    requested_amount_rub: 20000000,
    preapproved_amount_rub: 20000000,
    scored_limit_rub: 30000000,
  });
  expect(detail.application.product).toMatchObject({
    secured: false,
    required_documents: ["BANK_STATEMENT", "FINANCIAL_REPORT"],
  });
  expect(detail.application.latest_evaluation).toMatchObject({ rule: "R8", score: 100, risk: "low" });
  await officer.goto(`/?application=${id}`);
  await expect(statusPill(officer)).toHaveText("Предварительно одобрена");
  await expect(officer.locator("main")).toContainText("Кредит по ПСК для приграничных территорий");
});
