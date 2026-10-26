import { expect } from "@playwright/test";
import { test } from "./fixtures";
import {
  expectNoDemoWording,
  history,
  onboard,
  registerClient,
  submitApplication,
  termCard,
} from "./helpers";

// The client never learns the scoring (docs/application-states.md): no score, risk band or calculated limit on the
// status page, in its timeline or in what the API sends the client. The turnover estimate and the requested,
// preapproved and final amounts stay.
const SCORING = /балл|риск|скоринг|лимит/i;

test("the client's status page shows no score, risk or calculated limit; a smaller preliminary approval names only its amount", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await registerClient(page, "hidden-scoring");
  await onboard(page, "Сильный бизнес");
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await page.getByLabel("Сумма, ₽", { exact: true }).fill("3000000");
  await expect(page.locator(termCard)).toContainText(
    "Запрошенная сумма выше предварительной оценки",
  );
  // Low risk, 100 points, a 2 400 000 ₽ scored limit below the 3 000 000 ₽ asked (R9): none of it is shown.
  const id = await submitApplication(
    page,
    termCard,
    { debt: "160000", amount: "3000000" },
    "Заявка предварительно одобрена",
  );
  const result = page.locator(".status-result");
  await expect(result).toContainText(
    "Предварительно одобрена сумма 2 400 000 ₽ — меньше запрошенной",
  );
  await expect(result).not.toContainText(SCORING);
  await expect(result.locator("dt")).toHaveText(["Проверено"]);
  await expect(page.getByRole("list", { name: "История заявки" })).not.toContainText(SCORING);
  await expect(page.locator("main")).not.toContainText(/Скоринг|балл|Расчётный лимит|рассчитанн/i);
  await expect(page.getByRole("group", { name: "Запрошенная сумма" })).toContainText("3 000 000 ₽");
  await expect(page.getByRole("group", { name: "Предварительно одобрено" })).toContainText("2 400 000 ₽");
  await expect(
    page.getByRole("group", { name: "Предварительная оценка лимита" }),
  ).toContainText("Ориентир по обороту");
  await expectNoDemoWording(page);

  const body = (await (await page.request.get(`/api/v1/applications/${id}`)).json()).application;
  expect(body).not.toHaveProperty("scored_limit_rub");
  expect(Object.keys(body.latest_evaluation).sort()).toEqual(["created_at", "id", "outcome", "reasons"]);
  expect(JSON.stringify(body)).not.toMatch(SCORING);
  const items = await history(page, id);
  expect(items.map((item) => item.reason_code)).toEqual(["CREATED", "SUBMITTED", "CHECK_RESULT"]);
  expect(JSON.stringify(items)).not.toMatch(SCORING);
});
