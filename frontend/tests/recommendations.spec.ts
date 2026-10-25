import { test, expect, Page } from "@playwright/test";
import { artifacts, onboard, registerClient } from "./helpers";
const strong = "e230a446-129b-570f-b450-3cd8f7ddc8e5";
const term = '[data-product-id="alfa_term_loan_unsecured"]';
const line = '[data-product-id="alfa_revolving_line_unsecured"]';
async function open(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Демо-клиент", exact: true }).click();
  await page.getByLabel("Ваша компания", { exact: true }).selectOption(strong);
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await expect(page.locator(term)).toContainText("2 400 000 ₽");
}
// Card counts and catalog order come from the live catalog, never from a hard-coded product list.
async function catalogProducts(page: Page): Promise<{ id: string }[]> {
  return (await (await page.request.get("/api/v1/catalog")).json()).products;
}
test("recommendation calculator: every catalog product ranked by amount, with capacity, payment, alternatives and an immutable snapshot", async ({
  page,
}) => {
  await open(page);
  await expect(page.locator("article")).toHaveCount(
    (await catalogProducts(page)).length,
  );
  await expect(page.locator(".research-catalog")).toHaveCount(0);
  await expect(page.locator("article").first()).toHaveAttribute(
    "data-product-id",
    "alfa_term_loan_unsecured",
  );
  // 1 500 000 ₽: the 23.5% annuity over the 36-month estimate term, and the line's interest at full use.
  await expect(page.locator(term)).toContainText("58 456 ₽");
  await expect(page.locator(line)).toContainText("29 375 ₽");
  await page.locator(term).getByText("Все критерии соответствия").click();
  await expect(page.locator(term)).toContainText("Продукт доступен ИП и ООО");
  await page.setViewportSize({ width: 1440, height: 1500 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: artifacts + "/task-3-recommendations-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByLabel("Сумма, ₽", { exact: true }).fill("2500000");
  await expect(page.locator(term)).toContainText("Не соответствует параметрам");
  await expect(page.locator(term)).toContainText("Можно начать анкету");
  const snapshotText = await page.locator(".snapshot-note").innerText();
  const snapshotId = snapshotText.match(/Снимок ([a-f0-9-]+)/)![1];
  const saved = await page.request.get(
    `/api/v1/companies/${strong}/recommendations/${snapshotId}`,
  );
  expect(saved.status()).toBe(200);
  const snapshot = await saved.json();
  await page
    .locator(term)
    .getByRole("button", { name: "Рассчитать на 2 400 000 ₽" })
    .click();
  await expect(page.getByLabel("Сумма, ₽", { exact: true })).toHaveValue(
    "2400000",
  );
  await expect(page.locator(term)).toContainText("Соответствует потребности");
  expect(
    await (
      await page.request.get(
        `/api/v1/companies/${strong}/recommendations/${snapshotId}`,
      )
    ).json(),
  ).toEqual(snapshot);
  // A product that requires collateral waits for the pledge the questionnaire collects.
  await expect(
    page.locator('[data-product-id="alfa_term_loan_secured"]'),
  ).toContainText("Нужны сведения");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Найдём подходящий маршрут" }),
  ).toBeVisible();
  await expect(page.locator(term)).toBeVisible();
});
test("mobile calculator and accessible slider", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  const slider = page.getByRole("slider", { name: "Изменить сумму ползунком" });
  await slider.focus();
  await slider.press("ArrowRight");
  await expect(page.getByLabel("Сумма, ₽", { exact: true })).toHaveValue(
    "1550000",
  );
  await expect(page.locator(term)).toContainText("1 550 000 ₽");
  const overflow = await page.evaluate(() =>
    [...document.querySelectorAll("*")]
      .filter((el) => {
        const box = el.getBoundingClientRect();
        return box.right > innerWidth + 1 && box.width > 0;
      })
      .map((el) => ({
        tag: el.tagName,
        className: el.className,
        width: el.getBoundingClientRect().width,
        right: el.getBoundingClientRect().right,
      })),
  );
  expect(overflow).toEqual([]);
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: artifacts + "/task-3-recommendations-mobile.png",
    fullPage: true,
  });
  await page.getByLabel("Сумма, ₽", { exact: true }).fill("0");
  await expect(page.getByRole("alert")).toContainText(
    "целую положительную сумму",
  );
  await expect(page.locator("article")).toHaveCount(0);
});
for (const viewport of [
  { width: 1440, height: 800 },
  { width: 1366, height: 768 },
]) {
  test(`laptop ${viewport.width}x${viewport.height}: the pinned amount panel stays in the window and its controls are reachable by keyboard`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await open(page);
    const panel = page.locator(".need-panel");
    await page.evaluate(() => window.scrollTo(0, 700));
    await expect(page.locator(".recommendation-results")).toHaveAttribute(
      "aria-busy",
      "false",
    );
    const pinned = (await panel.boundingBox())!;
    expect(pinned.y).toBeGreaterThanOrEqual(0);
    expect(pinned.y + pinned.height).toBeLessThanOrEqual(viewport.height);
    await page.getByLabel("Сумма, ₽", { exact: true }).focus();
    await page.keyboard.press("Tab");
    await expect(
      page.getByRole("slider", { name: "Изменить сумму ползунком" }),
    ).toBeFocused();
    await expect(page.locator(":focus")).toBeInViewport({ ratio: 1 });
    await page.screenshot({
      path: `${artifacts}/task-3-fix1-laptop-${viewport.width}x${viewport.height}.png`,
    });
  });
}
test("late calculation cannot overwrite edited need or navigate across company views", async ({
  page,
}) => {
  await open(page);
  let release!: () => void;
  let started!: () => void;
  const held = new Promise<void>((r) => (release = r));
  const pending = new Promise<void>((r) => (started = r));
  await page.route(`**/companies/${strong}/recommendations`, async (route) => {
    if (route.request().postDataJSON().requested_amount_rub !== 2000000) {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    started();
    await held;
    await route.fulfill({ response }).catch(() => {});
  });
  await page.getByLabel("Сумма, ₽", { exact: true }).fill("2000000");
  await pending;
  await page.getByLabel("Сумма, ₽", { exact: true }).fill("1000000");
  await expect(page.locator(term)).toContainText("38 971 ₽");
  release();
  await expect(page.getByLabel("Сумма, ₽", { exact: true })).toHaveValue(
    "1000000",
  );
  await expect(page.locator(term)).toContainText("38 971 ₽");
  await page.getByRole("button", { name: "Профиль компании" }).click();
  await expect(
    page.getByRole("heading", { name: "ООО «Сильный бизнес»" }),
  ).toBeVisible();
  await expect(page.locator("article")).toHaveCount(0);
});

test("plain catalog mode keeps catalog order and the same figures without fit guidance", async ({
  page,
}) => {
  await open(page);
  const products = await catalogProducts(page);
  await expect(page.locator("article").first()).toHaveAttribute(
    "data-product-id",
    "alfa_term_loan_unsecured",
  );
  await page.getByLabel("Режим показа продуктов").selectOption("catalog");
  await expect(
    page.getByRole("heading", { name: "Каталог продуктов" }),
  ).toBeVisible();
  await expect(page.locator("article")).toHaveCount(products.length);
  for (const [index, product] of products.entries())
    await expect(page.locator("article").nth(index)).toHaveAttribute(
      "data-product-id",
      product.id,
    );
  await expect(page.locator(term)).toContainText("58 456 ₽");
  await expect(page.locator(line)).toContainText("29 375 ₽");
  await expect(page.locator(".product-rank")).toHaveCount(0);
  await expect(page.locator("article .status")).toHaveCount(0);
  await expect(page.locator(".fit-reasons")).toHaveCount(0);
  await expect(page.locator(".product-alternatives")).toHaveCount(0);
  await expect(page.getByText("Все критерии соответствия")).toHaveCount(0);
  await page.getByLabel("Режим показа продуктов").selectOption("guided");
  await expect(page.locator("article").first()).toHaveAttribute(
    "data-product-id",
    "alfa_term_loan_unsecured",
  );
  await expect(page.locator(".product-rank")).toHaveCount(products.length);
});

// Fresh synthetic clients keep these checks independent of the mutable seeded companies.
async function onboardFixture(page: Page, fixtureText: string) {
  await registerClient(page, "rec");
  await onboard(page, fixtureText);
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
}

test("inactive company gets read-only results with the failure reason and no application", async ({
  page,
}) => {
  await onboardFixture(page, "Неактивный бизнес");
  await expect(page.getByText("Компания не действует")).toBeVisible();
  await expect(page.locator("article")).toHaveCount(
    (await catalogProducts(page)).length,
  );
  for (const card of await page.locator("article").all()) {
    await expect(card).toContainText("Не соответствует параметрам");
    await expect(card).toContainText("Деятельность компании прекращена");
    await expect(card).toContainText("выберите действующую компанию");
    await expect(card).toContainText("Платёж не рассчитан");
  }
  await expect(page.getByText("Можно начать анкету")).toHaveCount(0);
});

test("unavailable registry shows unknown eligibility and recovers after the retry", async ({
  page,
}) => {
  await onboardFixture(page, "Реестр недоступен");
  await expect(
    page.getByText("Статус компании в реестре не подтверждён"),
  ).toBeVisible();
  await expect(page.locator("article")).toHaveCount(
    (await catalogProducts(page)).length,
  );
  await expect(page.locator(term)).toContainText("Нужны сведения");
  await expect(page.locator(term)).toContainText("2 400 000 ₽");
  await expect(page.getByText("Можно начать анкету")).toHaveCount(0);
  await expect(page.locator(term)).toContainText(
    "Повторите проверку реестра в профиле компании",
  );
  await page.getByRole("button", { name: "Профиль компании" }).click();
  await page.getByRole("button", { name: "Повторить проверку" }).click();
  await expect(
    page.getByText("Действующая компания", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await expect(page.locator(term)).toContainText("Соответствует потребности");
  await expect(page.locator(term)).toContainText("Можно начать анкету");
});

test("missing turnover keeps the cards, shows unknown estimates and asks for the data", async ({
  page,
}) => {
  await onboardFixture(page, "Неполные обороты");
  await expect(
    page.getByText("Нет положительных сведений об обороте"),
  ).toBeVisible();
  await expect(page.locator("article")).toHaveCount(
    (await catalogProducts(page)).length,
  );
  // Every personal estimate is unknown; the term loan explains why and still allows a draft.
  for (const card of await page.locator("article").all())
    await expect(card).toContainText("Нужно уточнить");
  for (const text of [
    "Нужны сведения",
    "Платёж не рассчитан",
    "Можно начать анкету",
    "Оборот неизвестен",
  ])
    await expect(page.locator(term)).toContainText(text);
});
