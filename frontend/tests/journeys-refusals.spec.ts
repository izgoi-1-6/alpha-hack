import { expect, Page } from "@playwright/test";
import { test } from "./fixtures";
import {
  decisionPanel,
  documentsCard,
  expectNoDemoWording,
  history,
  officerPage,
  onboard,
  openRecommendations,
  registerClient,
  requirementRow,
  revision,
  reviewDocument,
  reviewDocuments,
  securedCard,
  staffDetail,
  statusPill,
  submitApplication,
  termCard,
  uploadDocument,
} from "./helpers";
import { jpegFile, pdfFile, pngFile } from "./files";

// End-to-end journeys against the real app (Task 13): fresh synthetic clients, officer@demo.local in a browser
// context of its own, no injected replies.

const shot = (page: Page, name: string) =>
  page.screenshot({ path: `${revision}/task-13-${name}.png`, fullPage: true });
const heading = (page: Page, name: string) =>
  page.getByRole("heading", { level: 1, name });
const preapproved = "Заявка предварительно одобрена";
const rejected = "По заявке отказ";

test("journey 3 — three refusals: an automatic high-risk rejection, an officer's rejection where approval is a mandatory stop, and a final rejection at the document stage", async ({
  page,
  browser,
}) => {
  test.setTimeout(300_000);
  await registerClient(page, "journey-rejection");
  await onboard(page, "Высокий риск");
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await page.getByLabel("Сумма, ₽", { exact: true }).fill("300000");
  await expect(page.locator(termCard)).toContainText("Расчёт на сумму 300 000 ₽");

  // 1. Four months in business, falling turnover, a heavy debt load, a closed minor overdue: 10 points, R6.
  const automatic = await submitApplication(page, termCard, { debt: "180000" }, rejected);
  await expect(page.locator(".status-pill")).toHaveText("Отказ");
  await expect(page.locator(".status-next")).toContainText("Причина — в результате проверки ниже");
  await expect(page.locator(".status-result")).toContainText("Высокий риск по результатам скоринга");
  await expect(page.locator(".status-result")).toContainText("10 баллов");
  // A refusal shows no estimate that could read like available capacity, and offers a new choice instead of a cancel.
  await expect(page.getByRole("group", { name: "Предварительная оценка лимита" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Отменить заявку" })).toHaveCount(0);
  await expectNoDemoWording(page);
  await shot(page, "journey-rejected");
  expect((await history(page, automatic)).map((item) => item.reason_code)).toEqual([
    "CREATED",
    "SUBMITTED",
    "R6",
  ]);

  // 2. A new application for the same product (the refused one is closed), now with tax arrears: a specialist reviews
  // it (R5), but 10 points make a preliminary approval a mandatory stop — only a reasoned rejection remains.
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await page.getByLabel("Сумма, ₽", { exact: true }).fill("300000");
  await expect(page.locator(termCard)).toContainText("Расчёт на сумму 300 000 ₽");
  const reviewed = await submitApplication(
    page,
    termCard,
    { debt: "180000", taxDebt: "50000" },
    "Заявка на рассмотрении у специалиста",
  );
  const officer = await officerPage(browser);
  await officer.goto(`/?application=${reviewed}`);
  const decision = decisionPanel(officer);
  await decision.getByRole("button", { name: "Взять в работу" }).click();
  await expect(decision).toContainText("Ответственный: Я");
  await expect(decision).toContainText("Предварительное одобрение невозможно");
  await expect(decision).toContainText("Возможен только отказ с причиной");
  await expect(decision.getByRole("button", { name: "Предварительно одобрить" })).toHaveCount(0);
  expect((await staffDetail(officer, reviewed)).application.preapproval.blocked_by.code).toBe(
    "MANDATORY_STOP",
  );
  await decision.getByRole("button", { name: "Отказ", exact: true }).click();
  await expect(decision).toContainText("Предварительный отказ");
  const reason = "Высокий риск и налоговая задолженность: одобрение невозможно.";
  await decision.getByLabel("Причина отказа").fill(reason);
  await decision.getByRole("button", { name: "Отказать", exact: true }).click();
  // «Вернуться» from the confirmation gives focus back to the action.
  await decision.getByRole("button", { name: "Вернуться" }).click();
  await expect(decision.getByRole("button", { name: "Отказать", exact: true })).toBeFocused();
  await decision.getByRole("button", { name: "Отказать", exact: true }).click();
  await decision.getByRole("button", { name: "Да, отказать" }).click();
  await expect(statusPill(officer)).toHaveText("Отказ");
  await page.reload();
  await expect(heading(page, rejected)).toBeVisible();
  await expect(page.locator(".status-next")).toContainText("Решение принял кредитный специалист");
  await expect(page.locator(".officer-comment")).toContainText(reason);

  // 3. Another company of the same client reaches the document stage; the officer rejects one document, then the whole
  // application. The packet stays as a read-only record and no longer asks for a corrected file.
  await onboard(page, "Сильный бизнес");
  await openRecommendations(page);
  const documentStage = await submitApplication(page, termCard, { debt: "160000" }, preapproved);
  const card = documentsCard(page);
  await uploadDocument(requirementRow(card, "BANK_STATEMENT"), pdfFile("Выписка.pdf"));
  await uploadDocument(requirementRow(card, "FINANCIAL_REPORT"), pngFile("Отчётность.png"));
  await card.getByRole("button", { name: "Отправить комплект" }).click();
  await expect(heading(page, "Документы на проверке")).toBeVisible();
  await officer.goto(`/?application=${documentStage}`);
  await decision.getByRole("button", { name: "Взять в работу" }).click();
  await expect(decision).toContainText("Ответственный: Я");
  const documentReason = "Отчётность не за период анкеты.";
  await reviewDocument(officer, "FINANCIAL_REPORT", "Отклонить", documentReason);
  await expect(statusPill(officer)).toHaveText("Замена документов");
  await expect(decision).toContainText("Окончательный отказ");
  const finalReason = "Подтверждающие документы не представлены: отказываем на этапе документов.";
  await decision.getByLabel("Причина отказа").fill(finalReason);
  await decision.getByRole("button", { name: "Отказать", exact: true }).click();
  await decision.getByRole("button", { name: "Да, отказать" }).click();
  await expect(statusPill(officer)).toHaveText("Отказ");
  await page.reload();
  await expect(heading(page, rejected)).toBeVisible();
  await expect(page.locator(".officer-comment")).toContainText(finalReason);
  const report = requirementRow(card, "FINANCIAL_REPORT");
  await expect(report).toContainText("Отклонён");
  await expect(report).toContainText(documentReason);
  await expect(report).not.toContainText("Загрузите исправленный файл");
  await expect(card.getByRole("button", { name: /Загрузить файл|Заменить файл|Удалить файл|Отправить комплект/ })).toHaveCount(0);
  await expect(report.getByRole("link", { name: "Скачать файл «Отчётность.png»" })).toBeVisible();
  await expect(card).toContainText("Загрузка закрыта");
  await expectNoDemoWording(page);
  expect((await history(page, documentStage)).map((item) => item.reason_code)).toEqual([
    "CREATED",
    "SUBMITTED",
    "R8",
    "DOCUMENTS_SUBMITTED",
    "DOCUMENT_REJECTED",
    "FINAL_REJECTED",
  ]);
});

test("journey 5 — a secured loan's valuation is rejected and replaced; the officer's typed review survives a change made in another tab; the verified value bounds the final approval", async ({
  page,
  browser,
}) => {
  test.setTimeout(300_000);
  await registerClient(page, "journey-documents");
  await onboard(page, "Оборудование");
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await page.getByLabel("Сумма, ₽", { exact: true }).fill("4000000");
  // Before the questionnaire the pledge is unknown: the secured card needs it and shows no personal estimate yet.
  await expect(page.locator(".results-summary")).toContainText("для суммы 4 000 000 ₽");
  await expect(page.locator(".results-summary")).not.toContainText("Пересчитываем");
  await expect(page.locator(securedCard)).toContainText("Дополните сведения о залоге в анкете");
  const id = await submitApplication(
    page,
    securedCard,
    {
      purpose: "Развитие бизнеса",
      term: "36",
      debt: "300000",
      pledge: { value: "8000000", description: "Производственная линия" },
    },
    preapproved,
  );
  // Secured: the scored limit is min(3 × 1 500 000 ₽, 70% of the declared 8 000 000 ₽) = 4 500 000 ₽; four documents.
  await expect(page.locator(".status-result")).toContainText("4 500 000 ₽");
  const card = documentsCard(page);
  await expect(card.locator("[data-document-type]")).toHaveCount(4);
  await uploadDocument(requirementRow(card, "BANK_STATEMENT"), pdfFile("Выписка.pdf"));
  await uploadDocument(requirementRow(card, "FINANCIAL_REPORT"), pngFile("Баланс.png"));
  await uploadDocument(
    requirementRow(card, "COLLATERAL_OWNERSHIP"),
    await jpegFile(page, "Право собственности.jpg"),
  );
  await uploadDocument(requirementRow(card, "COLLATERAL_VALUATION"), pdfFile("Оценка 2025.pdf"));
  await card.getByRole("button", { name: "Отправить комплект" }).click();
  await expect(heading(page, "Документы на проверке")).toBeVisible();

  // The officer accepts the statement and the report, and sends the outdated valuation back.
  const officer = await officerPage(browser);
  await officer.goto(`/?application=${id}`);
  const decision = decisionPanel(officer);
  await decision.getByRole("button", { name: "Взять в работу" }).click();
  await expect(decision).toContainText("Ответственный: Я");
  await reviewDocument(officer, "BANK_STATEMENT", "Принять", "Обороты совпадают с анкетой.");
  await reviewDocument(officer, "FINANCIAL_REPORT", "Принять", "Отчётность за период анкеты.");
  const valuationReason = "Оценка старше шести месяцев: нужен свежий отчёт оценщика.";
  await reviewDocument(officer, "COLLATERAL_VALUATION", "Отклонить", valuationReason);
  await expect(statusPill(officer)).toHaveText("Замена документов");

  // The client replaces the valuation; the rejected file stays in the record.
  await page.reload();
  await expect(heading(page, "Нужно заменить документы")).toBeVisible();
  const valuation = requirementRow(card, "COLLATERAL_VALUATION");
  await expect(valuation).toContainText(valuationReason);
  await expect(valuation).toContainText("Загрузите исправленный файл вместо этого.");
  await uploadDocument(valuation, pdfFile("Оценка 2026.pdf"), "Заменить файл");
  await valuation.getByText("Прежние версии (1)").click();
  await expect(valuation.locator(".requirement-history li")).toContainText("Оценка 2025.pdf");
  await card.getByRole("button", { name: "Отправить комплект" }).click();
  await expect(heading(page, "Документы на проверке")).toBeVisible();

  // Two officer tabs: one types a review of the ownership document while the other accepts the valuation with its
  // verified value. The first tab's review meets the version conflict, reloads and keeps what was typed.
  await officer.reload();
  const second = await officer.context().newPage();
  await second.goto(`/?application=${id}`);
  const ownership = requirementRow(reviewDocuments(officer), "COLLATERAL_OWNERSHIP");
  await ownership.getByLabel("Принять", { exact: true }).check();
  const comment = "Право собственности подтверждено выпиской из реестра.";
  await ownership.getByLabel("Комментарий к проверке").fill(comment);
  await reviewDocument(second, "COLLATERAL_VALUATION", "Принять", "Свежая оценка проверена.", "5000000");
  await second.close();
  await ownership.getByRole("button", { name: "Принять документ" }).click();
  await expect(ownership.getByRole("alert")).toContainText("Заявка изменилась");
  await expect(ownership.getByLabel("Комментарий к проверке")).toHaveValue(comment);
  await expect(
    requirementRow(reviewDocuments(officer), "COLLATERAL_VALUATION").locator(".requirement-status"),
  ).toHaveText("Принят");
  await ownership.getByRole("button", { name: "Принять документ" }).click();
  await expect(ownership.locator(".requirement-status")).toHaveText("Принят");

  // 70% of the verified 5 000 000 ₽ bounds the final amount below the 4 000 000 ₽ preliminary approval.
  const amount = decision.getByLabel("Итоговая сумма, ₽");
  await expect(amount).toHaveValue("3500000");
  await expect(decision).toContainText("от 500 000 ₽ до 3 500 000 ₽");
  await decision.getByLabel("Основание решения").fill("Одобряем в пределах проверенной стоимости залога.");
  await decision.getByRole("button", { name: "Одобрить окончательно" }).click();
  await decision.getByRole("button", { name: "Да, одобрить" }).click();
  await expect(statusPill(officer)).toHaveText("Одобрена");
  const detail = await staffDetail(officer, id);
  expect(detail.application).toMatchObject({
    preapproved_amount_rub: 4000000,
    final_amount_rub: 3500000,
  });
  expect(
    detail.documents.filter((row: { document_type: string }) => row.document_type === "COLLATERAL_VALUATION"),
  ).toHaveLength(2);

  await page.reload();
  await expect(heading(page, "Заявка одобрена")).toBeVisible();
  await expect(page.getByRole("group", { name: "Предварительно одобрено" })).toContainText("4 000 000 ₽");
  await expect(page.getByRole("group", { name: "Итоговая сумма" })).toContainText("3 500 000 ₽");
  await expect(valuation).toContainText("Проверенная стоимость залога: 5 000 000 ₽");
  await expectNoDemoWording(page);
  await shot(page, "journey-secured-approved");
});
