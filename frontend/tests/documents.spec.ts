import { expect, Locator, Page } from "@playwright/test";
import { test } from "./fixtures";
import {
  artifacts,
  chooseDocument as choose,
  decisionPanel,
  documentsCard as documents,
  expectNoDemoWording,
  expectNoPageOverflow,
  expectTouchTargets,
  officerPage,
  onboard,
  openRecommendations,
  registerClient,
  requirementRow as requirement,
  reviewDocument as review,
  reviewDocuments,
  securedCard,
  settle,
  staffDetail,
  statusPill,
  submitApplication,
  termCard,
  uploadDocument as upload,
} from "./helpers";
import {
  htmlAsPdf,
  jpegFile,
  pdfFile,
  pngBytes,
  pngFile,
} from "./files";

// The document phase against the real API: synthetic files generated here, fresh synthetic clients, and
// officer@demo.local in a browser context of its own. Two replies are injected, each named where it happens: a lost
// upload response (the real API commits first) and one 413, which the browser's own size check otherwise prevents.

const preapproved = "Заявка предварительно одобрена";
const uploads = /\/api\/v1\/applications\/[^/]+\/documents$/;

async function application(page: Page, id: string) {
  const response = await page.request.get(`/api/v1/applications/${id}`);
  expect(response.status()).toBe(200);
  return (await response.json()).application;
}

async function checklist(page: Page, id: string) {
  const response = await page.request.get(`/api/v1/applications/${id}/documents`);
  expect(response.status()).toBe(200);
  return response.json();
}

async function downloaded(page: Page, link: Locator) {
  const download = page.waitForEvent("download");
  await link.click();
  const file = await download;
  const chunks: Buffer[] = [];
  for await (const chunk of await file.createReadStream()) chunks.push(chunk as Buffer);
  return { name: file.suggestedFilename(), bytes: Buffer.concat(chunks) };
}

test("A09 journey: preapproval → sequential uploads with progress → unsafe file refused → officer rejects one → replacement → all accepted → final approval → the Alfa-Business hand-off page", async ({
  page,
  browser,
}) => {
  test.setTimeout(240_000);
  await registerClient(page, "docs");
  await onboard(page, "Сильный бизнес");
  await openRecommendations(page);
  // 2 500 000 ₽ is above the 2 400 000 ₽ scored limit: preapproved for the limit (R9), so every amount differs.
  const id = await submitApplication(page, termCard, { amount: "2500000", debt: "160000" }, preapproved);
  const before = await application(page, id);
  expect(before.preapproved_amount_rub).toBe(2400000);

  const card = documents(page);
  await expect(card).toContainText("Проверка документов: тип и структура файла");
  await expect(card).toContainText("Это не антивирусная проверка");
  const deadline = card.locator(".documents-deadline");
  await expect(deadline).toContainText("Загрузка и замена документов срок не продлевают");
  const deadlineText = await deadline.innerText();
  await expect(card.getByRole("button", { name: "Отправить комплект" })).toHaveCount(0);
  const statement = requirement(card, "BANK_STATEMENT");
  const report = requirement(card, "FINANCIAL_REPORT");
  await expect(statement).toContainText("Банковская выписка");
  await expect(statement).toContainText("Не загружен");
  await expect(report).toContainText("Финансовая отчётность");

  // An HTML page renamed to .pdf passes the browser's type check and is refused by the server's content check.
  await choose(statement, htmlAsPdf("Выписка.pdf"));
  await expect(statement.getByRole("alert")).toContainText(
    "Содержимое файла не соответствует его типу",
  );
  await expect(statement).toContainText("Не загружен");

  // Two files chosen at once upload one after the other, each with the version the previous upload returned.
  const order: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && uploads.test(request.url())) order.push("sent");
  });
  page.on("response", (response) => {
    if (response.request().method() === "POST" && uploads.test(response.url()))
      order.push(`answered ${response.status()}`);
  });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", {
    offline: false,
    latency: 0,
    downloadThroughput: -1,
    uploadThroughput: 96 * 1024,
  });
  const statementFile = pdfFile("Выписка за сентябрь.pdf", { padding: 300_000 });
  await choose(statement, statementFile);
  const progress = statement.getByRole("progressbar");
  await expect(progress).toBeVisible();
  await expect(statement).toContainText("Загружаем");
  await choose(report, pngFile("Отчётность 2026.png"));
  await expect(report).toContainText("В очереди");
  await expect(card.getByRole("button", { name: "Отправить комплект" })).toHaveCount(0);
  await expect
    .poll(() => progress.evaluate((bar: HTMLProgressElement) => bar.value), { timeout: 5_000 })
    .toBeGreaterThan(0);
  await expect(statement.locator(".requirement-file")).toContainText(statementFile.name, { timeout: 30_000 });
  await cdp.send("Network.emulateNetworkConditions", {
    offline: false,
    latency: 0,
    downloadThroughput: -1,
    uploadThroughput: -1,
  });
  await expect(report.locator(".requirement-file")).toContainText("Отчётность 2026.png");
  await expect(page.locator(".application-live")).toContainText("Отчётность 2026.png");
  // The second upload left only after the first was answered, and both were stored: no stale version was sent.
  expect(order.slice(-4)).toEqual(["sent", "answered 201", "sent", "answered 201"]);
  expect((await application(page, id)).version).toBe(before.version + 2);
  await expect(statement).toContainText("PDF");
  await expect(report).toContainText("PNG");
  // A size keeps its number and unit on one line (U+00A0): the padded statement in КБ, the few-pixel PNG in bytes.
  expect(
    await statement.locator(".document-file-facts").textContent(),
  ).toMatch(/^PDF · \d+,\d КБ · /);
  expect(await report.locator(".document-file-facts").textContent()).toMatch(
    /^PNG · \d+ Б · /,
  );
  await expect(card.getByRole("alert")).toHaveCount(0);

  // The owner downloads exactly the stored bytes through the authorized API route.
  const own = await downloaded(page, statement.getByRole("link", { name: `Скачать файл «${statementFile.name}»` }));
  expect(own.bytes.equals(statementFile.buffer)).toBe(true);

  // Uploads never move the deadline.
  await expect(deadline).toHaveText(deadlineText);
  expect((await application(page, id)).preapproval_expires_at).toBe(before.preapproval_expires_at);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `${artifacts}/task-6b-checklist-desktop.png`, fullPage: true });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 390, height: 844 });
  await expectNoPageOverflow(page);
  await expectTouchTargets(page);
  await page.evaluate(() => window.scrollTo(0, 0));
  await settle(page);
  await page.screenshot({ path: `${artifacts}/task-6b-checklist-mobile.png`, fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });

  // Completion is offered only once the packet is whole; the submitted packet is frozen for review.
  await card.getByRole("button", { name: "Отправить комплект" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Документы на проверке" })).toBeFocused();
  await expect(card).toContainText("Комплект на проверке у кредитного специалиста");
  await expect(card.getByRole("button", { name: /Загрузить файл|Заменить файл|Удалить файл/ })).toHaveCount(0);
  await expect(statement.getByRole("link", { name: /Скачать файл/ })).toBeVisible();

  // The officer claims the case and inspects each document: metadata, the SHA-256 short form and the download.
  const officer = await officerPage(browser);
  await officer.goto(`/?application=${id}`);
  await expect(statusPill(officer)).toHaveText("Документы на проверке");
  const decision = decisionPanel(officer);
  await decision.getByRole("button", { name: "Взять в работу" }).click();
  await expect(decision).toContainText("Ответственный: Я");
  const staff = reviewDocuments(officer);
  await expect(staff).toContainText("Проверка документов: тип и структура файла");
  const staffStatement = requirement(staff, "BANK_STATEMENT");
  const detail = await staffDetail(officer, id);
  const stored = detail.documents.find((row: { document_type: string }) => row.document_type === "BANK_STATEMENT");
  await expect(staffStatement).toContainText(statementFile.name);
  await expect(staffStatement).toContainText("PDF");
  await expect(staffStatement).toContainText(stored.sha256.slice(0, 8));
  const copy = await downloaded(officer, staffStatement.getByRole("link", { name: `Скачать файл «${statementFile.name}»` }));
  expect(copy.bytes.equals(statementFile.buffer)).toBe(true);
  // Final approval waits for every document to be accepted.
  await expect(decision).toContainText("приняты все обязательные документы");
  await expect(decision.getByRole("button", { name: "Одобрить окончательно" })).toHaveCount(0);

  // The review form of one document, captured with a decision and a reason typed in.
  const staffReport = requirement(staff, "FINANCIAL_REPORT");
  await staffReport.getByLabel("Отклонить", { exact: true }).check();
  await staffReport.getByLabel("Причина отклонения").fill("Черновик причины.");
  await staff.scrollIntoViewIfNeeded();
  await staff.screenshot({ path: `${artifacts}/task-6b-officer-review-form.png` });
  await review(officer, "BANK_STATEMENT", "Принять", "Обороты по выписке совпадают с анкетой.");
  await expect(officer.locator(".officer-live")).toContainText("принят");
  const rejection = "Отчётность за другой период: нужна за период из анкеты.";
  await officer.evaluate(() => window.scrollTo(0, 0));
  await review(officer, "FINANCIAL_REPORT", "Отклонить", rejection);
  await expect(statusPill(officer)).toHaveText("Замена документов");
  await expect(requirement(staff, "FINANCIAL_REPORT")).toContainText(rejection);
  await staff.scrollIntoViewIfNeeded();
  await staff.screenshot({ path: `${artifacts}/task-6b-officer-documents.png` });

  // The customer sees the rework and the reason, cannot replace the accepted statement, and replaces the report.
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Нужно заменить документы" })).toBeVisible();
  await expect(report).toContainText("Отклонён");
  await expect(report).toContainText(rejection);
  await expect(statement).toContainText("Принят");
  await expect(statement.getByRole("button", { name: /Заменить файл|Удалить файл/ })).toHaveCount(0);
  await expect(card.getByRole("button", { name: "Отправить комплект" })).toHaveCount(0);
  const replacement = await jpegFile(page, "Отчётность за сентябрь.jpg");
  await upload(report, replacement, "Заменить файл");
  await expect(report).toContainText("JPEG");
  // The rejected file stays in the record as audit evidence, still downloadable.
  await report.getByText("Прежние версии (1)").click();
  const previous = report.locator(".requirement-history li");
  await expect(previous).toContainText("Отчётность 2026.png");
  await expect(previous).toContainText(rejection);
  const audit = await downloaded(page, previous.getByRole("link", { name: "Скачать файл «Отчётность 2026.png»" }));
  expect(audit.bytes.equals(pngBytes())).toBe(true);
  await card.getByRole("button", { name: "Отправить комплект" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Документы на проверке" })).toBeVisible();
  await expect(deadline).toHaveText(deadlineText);

  // All accepted: the final approval form opens at the server's upper bound with its bounds shown.
  await officer.reload();
  await review(officer, "FINANCIAL_REPORT", "Принять", "Отчётность за нужный период.");
  const amount = decision.getByLabel("Итоговая сумма, ₽");
  await expect(amount).toHaveValue("2400000");
  await expect(decision).toContainText("от 300 000 ₽ до 2 400 000 ₽");
  await amount.fill("2000000");
  const approval = "Документы приняты, одобряем 2 000 000 ₽.";
  await decision.getByLabel("Основание решения").fill(approval);
  await decision.getByRole("button", { name: "Одобрить окончательно" }).click();
  await expect(decision.getByRole("group", { name: "Одобрить заявку окончательно?" })).toBeVisible();
  await decision.screenshot({ path: `${artifacts}/task-6b-final-approve.png` });
  await decision.getByRole("button", { name: "Да, одобрить" }).click();
  await expect(statusPill(officer)).toHaveText("Одобрена");
  await expect(officer.getByRole("group", { name: "Итоговая сумма" })).toContainText("2 000 000 ₽");
  await expect(decision.getByRole("button")).toHaveCount(0);
  await expectNoDemoWording(officer);

  // The customer's outcome: the final decision, no money issued here, each amount on its own tile.
  await page.reload();
  await expect(
    page.getByRole("heading", { level: 1, name: "Заявка одобрена" }),
  ).toBeVisible();
  await expect(page.locator(".status-next")).toContainText("деньги не перечисляются");
  await expect(page.locator(".status-next")).toContainText(approval);
  await expect(page.getByRole("group", { name: "Запрошенная сумма" })).toContainText("2 500 000 ₽");
  await expect(page.getByRole("group", { name: "Предварительно одобрено" })).toContainText("2 400 000 ₽");
  const final = page.getByRole("group", { name: "Итоговая сумма" });
  await expect(final).toContainText("2 000 000 ₽");
  await expect(final).toContainText("деньги не перечисляются");
  await expect(card.getByRole("button", { name: /Загрузить файл|Заменить файл|Удалить файл/ })).toHaveCount(0);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `${artifacts}/task-6b-approved.png`, fullPage: true });
  await expectNoDemoWording(page);

  await page.getByRole("button", { name: "Перейти в Альфа-Бизнес" }).click();
  // The address bar shows the hand-off path right after the origin, with no demo segment.
  await expect(page).toHaveURL(new RegExp(`^https?://[^/]+/alfa-business/${id}$`));
  await expect(page.getByRole("heading", { level: 1, name: "Переход в Альфа-Бизнес" })).toBeVisible();
  const handoff = page.locator("main");
  await expect(handoff).toContainText("Деньги не перечисляются");
  await expect(handoff).toContainText("договор не подписывается");
  await expect(handoff).toContainText("2 000 000 ₽");
  await expect(handoff).toContainText("ООО «Сильный бизнес»");
  await page.screenshot({ path: `${artifacts}/task-6b-handoff.png`, fullPage: true });
  await expectNoDemoWording(page);
  await page.getByRole("button", { name: "Вернуться к заявке" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Заявка одобрена" }),
  ).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/");

  // An officer at the customer's hand-off address is refused; so is another client, for the page and the files.
  await officer.goto(`/alfa-business/${id}`);
  await expect(officer.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
  const downloadUrl = stored.download_url as string;
  await page.getByRole("button", { name: "Выйти из аккаунта" }).click();
  await registerClient(page, "docs-other");
  await page.goto(`/alfa-business/${id}`);
  await expect(page.getByRole("heading", { level: 1, name: "Страница недоступна" })).toBeVisible();
  await expect(page.locator("main")).not.toContainText("Сильный бизнес");
  await page.goto(`/?application=${id}`);
  await expect(page.getByRole("heading", { level: 1, name: "Заявка не найдена" })).toBeVisible();
  expect((await page.request.get(`/api/v1/applications/${id}/documents`)).status()).toBe(404);
  expect((await page.request.get(downloadUrl)).status()).toBe(404);
});

test("secured product: four documents, the valuation is accepted only with a verified value, which bounds the final approval", async ({
  page,
  browser,
}) => {
  test.setTimeout(240_000);
  await registerClient(page, "docs-secured");
  await onboard(page, "Оборудование");
  await openRecommendations(page);
  const id = await submitApplication(
    page,
    securedCard,
    { amount: "4000000", debt: "300000", pledge: { value: "8000000", description: "Производственная линия" } },
    preapproved,
  );
  const card = documents(page);
  for (const type of ["BANK_STATEMENT", "FINANCIAL_REPORT", "COLLATERAL_OWNERSHIP", "COLLATERAL_VALUATION"])
    await expect(requirement(card, type)).toContainText("Не загружен");
  await upload(requirement(card, "BANK_STATEMENT"), pdfFile("Выписка.pdf"));
  await upload(requirement(card, "FINANCIAL_REPORT"), pngFile("Баланс.png"));
  await upload(requirement(card, "COLLATERAL_OWNERSHIP"), await jpegFile(page, "Право собственности.jpg"));
  await upload(requirement(card, "COLLATERAL_VALUATION"), pdfFile("Оценка залога.pdf"));
  await card.getByRole("button", { name: "Отправить комплект" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Документы на проверке" })).toBeVisible();

  // Before the final decision the hand-off address explains that it is not available yet.
  await page.goto(`/alfa-business/${id}`);
  await expect(page.getByRole("heading", { level: 1, name: "Переход пока недоступен" })).toBeVisible();
  await page.getByRole("button", { name: "Открыть заявку" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Документы на проверке" })).toBeVisible();

  const officer = await officerPage(browser);
  await officer.goto(`/?application=${id}`);
  const decision = decisionPanel(officer);
  await decision.getByRole("button", { name: "Взять в работу" }).click();
  await expect(decision).toContainText("Ответственный: Я");
  for (const type of ["BANK_STATEMENT", "FINANCIAL_REPORT", "COLLATERAL_OWNERSHIP"]) {
    await review(officer, type, "Принять", "Документ соответствует заявке.");
  }
  // Accepting the valuation needs a positive whole-ruble verified value; nothing is sent without one.
  const valuation = requirement(reviewDocuments(officer), "COLLATERAL_VALUATION");
  await valuation.getByLabel("Принять", { exact: true }).check();
  await valuation.getByLabel("Комментарий к проверке").fill("Оценка проверена.");
  const value = valuation.getByLabel("Проверенная стоимость залога, ₽");
  await expect(value).toBeVisible();
  await expect(valuation.getByRole("button", { name: "Принять документ" })).toBeDisabled();
  await value.fill("5000000,5");
  await expect(valuation).toContainText("Введите целое число");
  await expect(valuation.getByRole("button", { name: "Принять документ" })).toBeDisabled();
  await value.fill("5000000");
  await valuation.getByRole("button", { name: "Принять документ" }).click();
  await expect(valuation.locator(".requirement-status")).toHaveText("Принят");
  await expect(valuation).toContainText("Проверенная стоимость залога: 5 000 000 ₽");
  const stored = (await staffDetail(officer, id)).documents.find(
    (row: { document_type: string }) => row.document_type === "COLLATERAL_VALUATION",
  );
  expect(stored).toMatchObject({ status: "ACCEPTED", verified_value_rub: 5000000 });

  // 70% of the verified 5 000 000 ₽ caps the final amount below the 4 000 000 ₽ preapproval.
  const amount = decision.getByLabel("Итоговая сумма, ₽");
  await expect(amount).toHaveValue("3500000");
  await expect(decision).toContainText("от 500 000 ₽ до 3 500 000 ₽");
  await expect(officer.getByRole("group", { name: "Допустимая итоговая сумма" })).toContainText("до 3 500 000 ₽");
  await amount.fill("4000000");
  await decision.getByLabel("Основание решения").fill("Одобряем в пределах проверенного залога.");
  // A version conflict (answered once by the route: with one officer every real version change here would close the
  // case) reloads the panel and keeps the typed amount and reason, since the approval is still offered.
  await officer.route(
    /\/officer\/applications\/[^/]+\/approve$/,
    (route) =>
      route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({
          error: { code: "VERSION_CONFLICT", message: "Заявка изменилась. Обновите данные и повторите действие." },
        }),
      }),
    { times: 1 },
  );
  await decision.getByRole("button", { name: "Одобрить окончательно" }).click();
  await decision.getByRole("button", { name: "Да, одобрить" }).click();
  await expect(decision.getByRole("alert")).toContainText("Введённые данные сохранены");
  await expect(amount).toHaveValue("4000000");
  await expect(decision.getByLabel("Основание решения")).toHaveValue("Одобряем в пределах проверенного залога.");
  // The confirmation is still open with the kept values: the repeat reaches the real server, which refuses the amount.
  await decision.getByRole("button", { name: "Да, одобрить" }).click();
  await expect(decision.locator("#approve-amount-error")).toContainText("до 3 500 000 ₽");
  await expect(decision.getByRole("alert")).toContainText("от 500 000 ₽ до 3 500 000 ₽");
  await expect(statusPill(officer)).toHaveText("Документы на проверке");
  await amount.fill("3500000");
  await decision.getByRole("button", { name: "Одобрить окончательно" }).click();
  await decision.getByRole("button", { name: "Да, одобрить" }).click();
  await expect(statusPill(officer)).toHaveText("Одобрена");

  // Direct navigation to the hand-off address now shows the hand-off; the customer sees the verified value.
  await page.goto(`/alfa-business/${id}`);
  await expect(page.getByRole("heading", { level: 1, name: "Переход в Альфа-Бизнес" })).toBeVisible();
  await expect(page.locator("main")).toContainText("3 500 000 ₽");
  await page.goto(`/?application=${id}`);
  await expect(page.getByRole("group", { name: "Итоговая сумма" })).toContainText("3 500 000 ₽");
  await expect(page.getByRole("group", { name: "Предварительно одобрено" })).toContainText("4 000 000 ₽");
  await expect(requirement(card, "COLLATERAL_VALUATION")).toContainText("Принят");
});

test("packet edits: browser checks, server refusals on the row, a lost upload replayed with its key, replacement and deletion; a final rejection leaves the packet read-only", async ({
  page,
  browser,
}) => {
  test.setTimeout(180_000);
  await registerClient(page, "docs-edit");
  await onboard(page, "Сильный бизнес");
  await openRecommendations(page);
  const id = await submitApplication(page, termCard, { amount: "2000000", debt: "160000" }, preapproved);
  const before = await application(page, id);
  const card = documents(page);
  const statement = requirement(card, "BANK_STATEMENT");
  const report = requirement(card, "FINANCIAL_REPORT");
  let posts = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && uploads.test(request.url())) posts += 1;
  });

  // The browser's own checks stop an unsupported type and an oversized file before anything is sent.
  await choose(statement, { name: "Выписка.docx", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer: Buffer.from("demo") });
  await expect(statement.getByRole("alert")).toContainText("PDF, JPEG или PNG");
  await choose(statement, { name: "Большая выписка.pdf", mimeType: "application/pdf", buffer: Buffer.alloc(20 * 1024 * 1024 + 1, 0x20) });
  await expect(statement.getByRole("alert")).toContainText("больше 20 МБ");
  expect(posts).toBe(0);

  // The server's refusals stay on the requirement they belong to.
  await choose(report, { name: "Отчёт.png", mimeType: "image/png", buffer: pngBytes().subarray(0, pngBytes().length - 20) });
  await expect(report.getByRole("alert")).toContainText("Изображение повреждено или обрезано");
  await expect(statement.getByRole("alert")).toContainText("больше 20 МБ");
  // A 413 the size check above prevents is answered once by the route, with the server's documented text.
  let injected = false;
  await page.route(uploads, (route) => {
    if (route.request().method() !== "POST" || injected) return route.fallback();
    injected = true;
    return route.fulfill({
      status: 413,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "FILE_TOO_LARGE", message: "Файл больше 20 МБ. Загрузите файл размером до 20 МБ." },
      }),
    });
  });
  await choose(report, pngFile("Отчёт.png"));
  await expect(report.getByRole("alert")).toContainText("Файл больше 20 МБ. Загрузите файл размером до 20 МБ.");
  expect(posts).toBe(2);

  // A lost response after the real API stored the file: the repeat reuses the key and the server replays it.
  const keys: string[] = [];
  await page.unroute(uploads);
  await page.route(uploads, async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    keys.push(route.request().headers()["idempotency-key"]);
    const response = await route.fetch();
    if (keys.length === 1) await route.abort();
    else await route.fulfill({ response });
  });
  const first = pdfFile("Выписка v1.pdf", { text: "First synthetic statement" });
  await choose(statement, first);
  await expect(statement.getByRole("alert")).toContainText("Нет связи с сервером");
  await statement.getByRole("button", { name: "Повторить загрузку" }).click();
  await expect(statement.locator(".requirement-file")).toContainText(first.name);
  await page.unroute(uploads);
  expect(keys).toHaveLength(2);
  expect(keys[1]).toBe(keys[0]);
  expect((await checklist(page, id)).items).toHaveLength(1);

  // Replacing an unreviewed file supersedes it; the earlier revision stays listed and downloadable.
  const second = pdfFile("Выписка v2.pdf", { text: "Second synthetic statement" });
  await upload(statement, second, "Заменить файл");
  await statement.getByText("Прежние версии (1)").click();
  const earlier = statement.locator(".requirement-history li");
  await expect(earlier).toContainText(first.name);
  await expect(earlier).toContainText("Заменён");
  const old = await downloaded(page, earlier.getByRole("link", { name: `Скачать файл «${first.name}»` }));
  expect(old.bytes.equals(first.buffer)).toBe(true);

  // Deleting the current file asks first; the requirement is empty again and the deletion is recorded.
  await statement.getByRole("button", { name: "Удалить файл" }).click();
  await statement.getByRole("button", { name: "Да, удалить" }).click();
  await expect(statement).toContainText("Не загружен");
  await expect(page.locator(".application-live")).toContainText("удалён");
  await expect(statement.getByText("Прежние версии (2)")).toBeVisible();
  await expect(card.getByRole("button", { name: "Отправить комплект" })).toHaveCount(0);
  await upload(report, pngFile("Отчёт.png"));
  expect((await application(page, id)).preapproval_expires_at).toBe(before.preapproval_expires_at);

  // The officer may refuse at the document stage whatever the packet holds: a confirmed final rejection.
  const officer = await officerPage(browser);
  await officer.goto(`/?application=${id}`);
  const decision = decisionPanel(officer);
  await decision.getByRole("button", { name: "Взять в работу" }).click();
  await expect(decision).toContainText("Окончательный отказ");
  const reason = "Выписка не загружена в срок, отказываем на этапе документов.";
  await decision.getByLabel("Причина отказа").fill(reason);
  await decision.getByRole("button", { name: "Отказать", exact: true }).click();
  await decision.getByRole("button", { name: "Да, отказать" }).click();
  await expect(statusPill(officer)).toHaveText("Отказ");
  await expect(officer.getByRole("region", { name: "Решения специалиста" })).toContainText("Отказ · окончательный");

  // The customer sees the reason; the packet is read-only but its files stay downloadable.
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "По заявке отказ" })).toBeVisible();
  await expect(page.locator(".status-next")).toContainText(reason);
  await expect(card.getByRole("button", { name: /Загрузить файл|Заменить файл|Удалить файл|Отправить комплект/ })).toHaveCount(0);
  await expect(report.getByRole("link", { name: "Скачать файл «Отчёт.png»" })).toBeVisible();
  await page.goto(`/alfa-business/${id}`);
  await expect(page.getByRole("heading", { level: 1, name: "Переход пока недоступен" })).toBeVisible();
});

test("one lock for uploads and deletions; a lost upload repeated after the page learnt a newer version is still the same upload; the delete confirmation keeps keyboard focus", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await registerClient(page, "docs-lock");
  await onboard(page, "Сильный бизнес");
  await openRecommendations(page);
  const id = await submitApplication(page, termCard, { amount: "2000000", debt: "160000" }, preapproved);
  const card = documents(page);
  const statement = requirement(card, "BANK_STATEMENT");
  const report = requirement(card, "FINANCIAL_REPORT");

  // The statement's answer is lost after the real API stored it; the report then meets the version that upload made.
  const sent: { key: string; version: string }[] = [];
  await page.route(uploads, async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const version = /name="version"\r\n\r\n(\d+)/.exec(route.request().postData() ?? "")?.[1] ?? "";
    sent.push({ key: route.request().headers()["idempotency-key"], version });
    const response = await route.fetch();
    if (sent.length === 1) await route.abort();
    else await route.fulfill({ response });
  });
  const first = pdfFile("Выписка.pdf", { text: "Synthetic statement" });
  await choose(statement, first);
  await expect(statement.getByRole("alert")).toContainText("Нет связи с сервером");
  await choose(report, pngFile("Отчёт.png"));
  await expect(report.getByRole("alert")).toContainText("Заявка изменилась");
  // The repeat is the same upload — its key and its version — so the server replays it instead of storing a copy.
  await statement.getByRole("button", { name: "Повторить загрузку" }).click();
  await expect(statement.locator(".requirement-file")).toContainText(first.name);
  expect(sent).toHaveLength(3);
  expect(sent[2]).toEqual(sent[0]);
  const stored = (await checklist(page, id)).items.filter(
    (item: { document_type: string }) => item.document_type === "BANK_STATEMENT",
  );
  expect(stored).toHaveLength(1);
  await report.getByRole("button", { name: "Повторить загрузку" }).click();
  await expect(report.locator(".requirement-file")).toContainText("Отчёт.png");
  await page.unroute(uploads);

  // The delete confirmation takes focus and gives it back to «Удалить файл» when the client keeps the file.
  await report.getByRole("button", { name: "Удалить файл" }).click();
  await expect(report.getByRole("button", { name: "Оставить" })).toBeFocused();
  await report.getByRole("button", { name: "Оставить" }).click();
  await expect(report.getByRole("button", { name: "Удалить файл" })).toBeFocused();

  // While one row deletes, nothing else may change the version: the other row cannot start an upload.
  let release!: () => void;
  const held = new Promise<void>((done) => (release = done));
  await page.route(/\/documents\/[^/]+$/, async (route) => {
    if (route.request().method() !== "DELETE") return route.fallback();
    await held;
    await route.continue();
  });
  await statement.getByRole("button", { name: "Удалить файл" }).click();
  await statement.getByRole("button", { name: "Да, удалить" }).click();
  await expect(report.getByRole("button", { name: "Заменить файл" })).toBeDisabled();
  await expect(report.getByRole("button", { name: "Удалить файл" })).toBeDisabled();
  release();
  await expect(statement).toContainText("Не загружен");
  // Focus goes to the upload that replaces the deleted file.
  await expect(statement.getByRole("button", { name: "Загрузить файл" })).toBeFocused();
  await expect(report.getByRole("button", { name: "Заменить файл" })).toBeEnabled();
  await page.unroute(/\/documents\/[^/]+$/);
});
