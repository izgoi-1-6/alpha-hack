import { test, expect, Page } from "@playwright/test";
const artifacts = "../.superpowers/sdd/2026-10-24-credit-route";
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
test("recommendation calculator: ranking, capacity, payment, alternatives and immutable snapshot", async ({
  page,
}) => {
  await open(page);
  await expect(page.locator("article").first()).toHaveAttribute(
    "data-product-id",
    "alfa_term_loan_unsecured",
  );
  await expect(page.locator(term)).toContainText("141 477 ₽");
  await expect(page.locator(line)).toContainText("30 000 ₽");
  await page.locator(term).getByText("Все критерии соответствия").click();
  await expect(page.locator(term)).toContainText("Продукт доступен ИП и ООО");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: artifacts + "/task-3-recommendations-desktop.png",
    fullPage: true,
  });
  await page.getByLabel("По мере необходимости").check();
  await expect(page.locator("article").first()).toHaveAttribute(
    "data-product-id",
    "alfa_revolving_line_unsecured",
  );
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
  await page.getByLabel("Цель финансирования").selectOption("investment");
  await expect(page.locator("article").first()).toHaveAttribute(
    "data-product-id",
    "alfa_term_loan_secured",
  );
  await expect(page.locator("article").first()).toContainText("Нужны сведения");
  await page.getByText("Исследовательский каталог", { exact: false }).click();
  // Nine archive entries exist; three reuse supported product ids and are not repeated.
  await expect(page.locator(".research-catalog li")).toHaveCount(6);
  await expect(page.locator(".research-catalog")).toContainText(
    "не принимают заявки",
  );
  await expect(page.locator(".research-catalog")).not.toContainText(
    "Кредит одной суммой без залога",
  );
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Найдём подходящий маршрут" }),
  ).toBeVisible();
  await expect(page.locator(term)).toBeVisible();
});
test("mobile calculator, accessible slider and declared collateral", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  const slider = page.getByRole("slider", { name: "Изменить сумму ползунком" });
  await slider.focus();
  await slider.press("ArrowRight");
  await expect(page.getByLabel("Сумма, ₽", { exact: true })).toHaveValue(
    "1550000",
  );
  await page.getByLabel("Есть ли залог?").selectOption("declared");
  await page.getByLabel("Заявленная стоимость, ₽").fill("4000000");
  await page.getByLabel("Описание залога").fill("Демо склад");
  await page.getByLabel("Подтверждаю собственность на залог").check();
  const secured = page.locator('[data-product-id="alfa_term_loan_secured"]');
  await expect(secured).toContainText("Соответствует потребности");
  await expect(secured).toContainText("2 400 000 ₽");
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
  await expect(page.locator(term)).toContainText("94 318 ₽");
  release();
  await expect(page.getByLabel("Сумма, ₽", { exact: true })).toHaveValue(
    "1000000",
  );
  await expect(page.locator(term)).toContainText("94 318 ₽");
  await page.getByRole("button", { name: "Профиль компании" }).click();
  await expect(
    page.getByRole("heading", { name: "ООО «Демо Сильный бизнес»" }),
  ).toBeVisible();
  await expect(page.locator("article")).toHaveCount(0);
});

test("plain catalog mode keeps catalog order and the same figures without fit guidance", async ({
  page,
}) => {
  await open(page);
  await page.getByLabel("По мере необходимости").check();
  await expect(page.locator("article").first()).toHaveAttribute(
    "data-product-id",
    "alfa_revolving_line_unsecured",
  );
  await page.getByLabel("Режим показа продуктов").selectOption("catalog");
  await expect(
    page.getByRole("heading", { name: "Каталог продуктов" }),
  ).toBeVisible();
  await expect(page.locator("article")).toHaveCount(3);
  for (const [index, id] of [
    "alfa_term_loan_unsecured",
    "alfa_revolving_line_unsecured",
    "alfa_term_loan_secured",
  ].entries())
    await expect(page.locator("article").nth(index)).toHaveAttribute(
      "data-product-id",
      id,
    );
  await expect(page.locator(term)).toContainText("141 477 ₽");
  await expect(page.locator(line)).toContainText("30 000 ₽");
  await expect(page.locator(".product-rank")).toHaveCount(0);
  await expect(page.locator("article .status")).toHaveCount(0);
  await expect(page.locator(".fit-reasons")).toHaveCount(0);
  await expect(page.locator(".product-alternatives")).toHaveCount(0);
  await expect(page.getByText("Все критерии соответствия")).toHaveCount(0);
  await page.getByLabel("Режим показа продуктов").selectOption("guided");
  await expect(page.locator("article").first()).toHaveAttribute(
    "data-product-id",
    "alfa_revolving_line_unsecured",
  );
  await expect(page.locator(".product-rank")).toHaveCount(3);
});

// Fresh synthetic clients keep these checks independent of the mutable seeded companies.
async function onboardFixture(page: Page, fixtureText: string) {
  await page.goto("/");
  await page.getByRole("button", { name: "Регистрация", exact: true }).click();
  await page.getByLabel("Ваше имя").fill("Демо Предприниматель");
  await page
    .getByLabel("Электронная почта")
    .fill(
      `rec-${Date.now()}-${Math.random().toString(36).slice(2)}@example.test`,
    );
  await page.getByLabel("Пароль", { exact: true }).fill("DemoCredit2026!");
  await page
    .getByRole("button", { name: "Создать аккаунт", exact: true })
    .click();
  await page
    .getByRole("main")
    .getByRole("button", { name: "Добавить компанию", exact: true })
    .click();
  await page.getByRole("button").filter({ hasText: fixtureText }).click();
  for (const checkbox of await page.getByRole("checkbox").all())
    await checkbox.check();
  await page.getByRole("button", { name: "Добавить и проверить" }).click();
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
}

test("inactive company gets read-only results with the failure reason and no application", async ({
  page,
}) => {
  await onboardFixture(page, "Неактивный бизнес");
  await expect(page.getByText("Компания не действует")).toBeVisible();
  await expect(page.locator("article")).toHaveCount(3);
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
  await expect(page.locator("article")).toHaveCount(3);
  for (const card of await page.locator("article").all())
    await expect(card).toContainText("Нужны сведения");
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
  await expect(page.locator("article")).toHaveCount(3);
  for (const card of await page.locator("article").all()) {
    await expect(card).toContainText("Нужны сведения");
    await expect(card).toContainText("Нужно уточнить");
    await expect(card).toContainText("Платёж не рассчитан");
    await expect(card).toContainText("Можно начать анкету");
  }
  await expect(page.locator(term)).toContainText("Оборот неизвестен");
});
