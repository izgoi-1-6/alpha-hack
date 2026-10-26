import { expect, Locator, Page } from "@playwright/test";
import { test } from "./fixtures";
import {
  expectNoPageOverflow,
  lineCard,
  loginClient,
  nbsp,
  onboard,
  registerClient,
  artifacts,
  settle,
  termCard,
} from "./helpers";

// The product-choice screen against the real API. The seeded client's strong company is only read here: a
// calculation saves a recommendation snapshot, never an application.
const strong = "e230a446-129b-570f-b450-3cd8f7ddc8e5";
const amountField = (page: Page) =>
  page.getByLabel("Сумма, ₽", { exact: true });
const slider = (page: Page) =>
  page.getByRole("slider", { name: "Сумма финансирования" });
const cards = (page: Page) => page.locator("article[data-product-id]");

type Product = {
  id: string;
  name: string;
  kind: string;
  display: { summary: string; features: string[]; best_for: string };
  amount_max_rub: number;
  term_min_months: number | null;
  term_max_months: number | null;
  annual_rate_bps: number | null;
  rate_certainty: string;
  conditions_to_confirm: { text: string }[];
};
type Item = {
  product_id: string;
  status: "fits" | "needs_info" | "does_not_fit";
  can_apply: boolean;
  indicative_limit_rub: number | null;
  estimated_payment_rub: number | null;
  payment_label: string | null;
  badges: { text: string }[];
};
type Catalog = {
  products: Product[];
  amount_slider: {
    min_rub: number;
    max_rub: number;
    default_rub: number;
    presets_rub: number[];
  };
};

// Card counts, order and texts come from the live catalog and the saved snapshot, never from a product list here.
async function catalogOf(page: Page): Promise<Catalog> {
  return (await page.request.get("/api/v1/catalog")).json();
}
/** «2 000 000» as the field shows it; «2 000 000 ₽» with `currency`. */
const grouped = (amount: number, currency = false) =>
  nbsp(
    amount.toLocaleString("ru-RU").replace(/\s/g, " ") + (currency ? " ₽" : ""),
  );
const compact = (amount: number) =>
  nbsp(
    new Intl.NumberFormat("ru-RU", {
      notation: "compact",
      maximumFractionDigits: 1,
    })
      .format(amount)
      .replace(/\s/g, " ") + " ₽",
  );

function calculated(page: Page, company = strong) {
  return page.waitForResponse(
    (response) =>
      response.url().endsWith(`/companies/${company}/recommendations`) &&
      response.request().method() === "POST" &&
      response.status() === 201,
  );
}

async function open(page: Page) {
  await page.goto("/");
  await loginClient(page);
  await page.getByLabel("Ваша компания", { exact: true }).selectOption(strong);
  const result = calculated(page);
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  const snapshot = (await (await result).json()) as {
    items: Item[];
    snapshot_id: string;
  };
  await expect(page.locator(termCard)).toBeVisible();
  return snapshot;
}

/** Sets the range input as a pointer drag would: the browser's own value setter and an input event. */
async function drag(range: Locator, position: number) {
  await range.evaluate((element: HTMLInputElement, value) => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(element, String(value));
    element.dispatchEvent(new Event("input", { bubbles: true }));
  }, position);
}

test("product choice: one amount control from the catalog config, every catalog product in the server's order, each card explained", async ({
  page,
}) => {
  const catalog = await catalogOf(page);
  const snapshot = await open(page);
  // The amount is the only input of the screen (its field and its slider); it starts at the configured default.
  await expect(
    page.locator("main").locator("input, select, textarea"),
  ).toHaveCount(2);
  await expect(amountField(page)).toHaveValue(
    grouped(catalog.amount_slider.default_rub),
  );
  await expect(slider(page)).toHaveAttribute(
    "aria-valuetext",
    grouped(catalog.amount_slider.default_rub, true),
  );
  // No need panel, no catalog mode switch, no research list.
  await expect(page.locator(".need-panel")).toHaveCount(0);
  await expect(page.getByLabel("Режим показа продуктов")).toHaveCount(0);
  await expect(page.locator(".research-catalog")).toHaveCount(0);

  // Every catalog product is one card, in the order the server ranked them.
  expect(snapshot.items.map((item) => item.product_id).sort()).toEqual(
    catalog.products.map((product) => product.id).sort(),
  );
  await expect(cards(page)).toHaveCount(catalog.products.length);
  expect(
    await cards(page).evaluateAll((elements) =>
      elements.map((element) => (element as HTMLElement).dataset.productId),
    ),
  ).toEqual(snapshot.items.map((item) => item.product_id));

  const labels = {
    fits: "Соответствует потребности",
    needs_info: "Нужны сведения",
    does_not_fit: "Не соответствует параметрам",
  };
  for (const product of catalog.products) {
    const item = snapshot.items.find(
      (entry) => entry.product_id === product.id,
    )!;
    const card = page.locator(`[data-product-id="${product.id}"]`);
    await expect(card.getByRole("heading", { level: 3 })).toHaveText(
      product.name,
    );
    for (const heading of ["Что это", "Особенности", "Кому подходит"])
      await expect(
        card.getByRole("heading", { level: 4, name: heading }),
      ).toBeVisible();
    // The explanations are the catalog's own display texts.
    await expect(card.locator(".product-summary")).toHaveText(
      product.display.summary,
    );
    await expect(card.locator(".product-features li")).toHaveText(
      product.display.features,
    );
    await expect(card.locator(".product-best-for")).toHaveText(
      product.display.best_for,
    );
    await expect(card.locator(".product-status")).toHaveText(
      labels[item.status],
    );
    // The personal estimate and the product maximum are two different figures.
    const estimate = card.getByRole("group", {
      name: "Личная предварительная оценка",
    });
    await expect(estimate).toContainText(
      item.indicative_limit_rub === null
        ? "Нужно уточнить"
        : grouped(item.indicative_limit_rub, true),
    );
    await expect(estimate).toContainText(
      "Максимум продукта " + grouped(product.amount_max_rub, true),
    );
    // Money keeps its digit groups and the ruble sign on one line (non-breaking spaces, not just normalised text).
    expect(await estimate.innerText()).toContain(
      grouped(product.amount_max_rub, true),
    );
    const terms = card.locator(".product-terms");
    await expect(terms).toContainText(
      product.annual_rate_bps === null
        ? "Ставка уточняется"
        : `${(product.annual_rate_bps / 100).toLocaleString("ru-RU")}% годовых`,
    );
    await expect(terms).toContainText(
      product.term_min_months === null
        ? "бессрочно"
        : `${product.term_min_months}–${product.term_max_months} мес.`,
    );
    const payment = card.locator(".product-payment");
    await expect(payment).toContainText(
      item.estimated_payment_rub === null
        ? "Не рассчитан"
        : grouped(item.estimated_payment_rub, true),
    );
    if (item.payment_label)
      await expect(payment).toContainText(item.payment_label);
    for (const badge of item.badges)
      await expect(card.locator(".product-badges")).toContainText(badge.text);
    // «Условия программы» opens the conditions the bank confirms during the review.
    const conditions = card.locator(".product-conditions");
    await conditions.getByText("Условия программы").click();
    for (const condition of product.conditions_to_confirm)
      await expect(conditions).toContainText(condition.text);
    await expect(
      card.getByRole("button", { name: "Начать анкету" }),
    ).toHaveCount(item.can_apply ? 1 : 0);
    // Eleven buttons share a name: each is described by its product's title.
    if (item.can_apply)
      await expect(
        card.getByRole("button", { name: "Начать анкету" }),
      ).toHaveAccessibleDescription(product.name);
  }
  // A preferential rate labels its payment with the period.
  await expect(
    page.locator('[data-product-id="psk_working_capital"] .product-payment'),
  ).toContainText("в льготный период 12 мес.");
  await expect(
    page
      .locator('[data-product-id="psk_working_capital"]')
      .getByText("Госпрограмма"),
  ).toBeVisible();

  // Above the personal estimate the card says so and offers the estimate; the earlier snapshot stays immutable.
  await amountField(page).fill("2500000");
  await expect(page.locator(termCard)).toContainText(
    "Не соответствует параметрам",
  );
  await expect(page.locator(termCard)).toContainText("Можно начать анкету");
  const note = await page.locator(".snapshot-note").innerText();
  const snapshotId = note.match(/Снимок ([a-f0-9-]+)/)![1];
  const saved = await (
    await page.request.get(
      `/api/v1/companies/${strong}/recommendations/${snapshotId}`,
    )
  ).json();
  await page
    .locator(termCard)
    .getByRole("button", { name: "Рассчитать на " + grouped(2400000, true) })
    .click();
  await expect(amountField(page)).toHaveValue(grouped(2400000));
  // The pressed button is replaced by the new results: focus moves to the slider of the amount that changed (not the
  // text field, which would open a phone's keyboard).
  await expect(slider(page)).toBeFocused();
  await expect(page.locator(termCard)).toContainText(
    "Соответствует потребности",
  );
  expect(
    await (
      await page.request.get(
        `/api/v1/companies/${strong}/recommendations/${snapshotId}`,
      )
    ).json(),
  ).toEqual(saved);
  // A card outside only by the amount offers the product's bound: the subsidy program starts at 25 000 000 ₽.
  const subsidy = page.locator('[data-product-id="psk_invest_subsidy"]');
  await expect(subsidy.locator(".product-fit")).toContainText(
    "Минимальная сумма: " + grouped(25000000, true),
  );
  await subsidy
    .getByRole("button", { name: "Рассчитать на " + grouped(25000000, true) })
    .click();
  await expect(amountField(page)).toHaveValue(grouped(25000000));
  await expect(subsidy.locator(".product-fit")).not.toContainText(
    "Минимальная сумма",
  );
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Найдём подходящий маршрут" }),
  ).toBeVisible();
  await expect(page.locator(termCard)).toBeVisible();
});

test("amount slider: log scale from the config, exact snapping, keyboard, presets and a typed value in sync", async ({
  page,
}) => {
  const { amount_slider: config } = await catalogOf(page);
  await open(page);
  const range = slider(page);
  const field = amountField(page);
  const shows = async (amount: number) => {
    await expect(field).toHaveValue(grouped(amount));
    await expect(range).toHaveAttribute(
      "aria-valuetext",
      grouped(amount, true),
    );
  };
  // Track positions follow ln(amount) between the configured bounds; snapping hits these amounts exactly.
  expect(await range.getAttribute("min")).toBe("0");
  const steps = Number(await range.getAttribute("max"));
  const span = Math.log(config.max_rub / config.min_rub);
  const position = (amount: number) =>
    Math.round((steps * Math.log(amount / config.min_rub)) / span);
  for (const amount of [config.min_rub, 500000, 25000000]) {
    for (const offset of [-1, 0, 1]) {
      await drag(range, Math.max(0, position(amount) + offset));
      await shows(amount);
    }
  }
  await drag(range, steps);
  await shows(config.max_rub);

  // Keyboard: arrows move one snapped step, PageUp/PageDown ten, Home/End to the bounds.
  await range.focus();
  await range.press("Home");
  await shows(config.min_rub);
  await range.press("ArrowRight");
  await shows(350000);
  for (let i = 0; i < 3; i += 1) await range.press("ArrowRight");
  await shows(500000);
  await range.press("ArrowUp");
  await shows(550000);
  await range.press("PageUp");
  await shows(1100000);
  await range.press("ArrowLeft");
  await shows(1000000);
  await range.press("ArrowDown");
  await shows(950000);
  await range.press("PageDown");
  await shows(450000);
  await range.press("End");
  await shows(config.max_rub);
  await range.press("ArrowLeft");
  await shows(1990000000);
  await range.press("PageDown");
  await shows(1890000000);

  // A typed amount is kept exactly, moves the slider, and the next arrow press snaps to the grid.
  await field.fill("24 000 000");
  await expect(range).toHaveAttribute(
    "aria-valuetext",
    grouped(24000000, true),
  );
  await range.press("ArrowRight");
  await shows(25000000);
  await field.fill("1234567");
  await expect(range).toHaveAttribute("aria-valuetext", grouped(1234567, true));
  await expect(page.locator(termCard)).toContainText(
    "Расчёт на сумму " + grouped(1234567, true),
  );
  await field.blur();
  await expect(field).toHaveValue(grouped(1234567));

  // Presets are the configured amounts; the chosen one is pressed and recalculates the cards.
  const presets = page
    .getByRole("group", { name: "Быстрый выбор суммы" })
    .getByRole("button");
  await expect(presets).toHaveText(config.presets_rub.map(compact));
  await presets.filter({ hasText: compact(10000000) }).click();
  await shows(10000000);
  await expect(presets.filter({ hasText: compact(10000000) })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(presets.filter({ hasText: compact(3000000) })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  await expect(page.locator(termCard)).toContainText(
    "Не соответствует параметрам",
  );
  await expect(page.locator(".results-summary")).toContainText(
    grouped(10000000, true),
  );

  // The typed value is checked against the configured bounds: nothing outside them is calculated.
  for (const [typed, message] of [
    ["100000", "Минимальная сумма — " + grouped(300000, true)],
    ["3000000000", "Максимальная сумма — " + grouped(2000000000, true)],
    ["два миллиона", "Введите сумму цифрами"],
  ]) {
    await field.fill(typed);
    await expect(page.getByRole("alert")).toContainText(message);
    await expect(cards(page)).toHaveCount(0);
  }
  await field.fill("3000000");
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(presets.filter({ hasText: compact(3000000) })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(cards(page).first()).toBeVisible();
  await field.blur();
  await expect(field).toHaveValue(grouped(3000000));
  await page
    .locator(".amount-picker")
    .screenshot({ path: `${artifacts}/slider.png` });
});

/** The term loan's annuity, rounded half up, in exact integer arithmetic: A·p·(q+p)ⁿ / (q·((q+p)ⁿ − qⁿ)), q = 120 000. */
function annuity(amount: number, bps: number, months: number) {
  const [a, p, q] = [BigInt(amount), BigInt(bps), 120_000n];
  const grown = (q + p) ** BigInt(months);
  const numerator = a * p * grown;
  const denominator = q * (grown - q ** BigInt(months));
  return Number((2n * numerator + denominator) / (2n * denominator));
}
/** A month's interest on a fully used line, rounded up. */
const lineInterest = (amount: number, bps: number) =>
  Math.ceil((amount * bps) / 120_000);

test("the default amount's cards: payments match an independent calculation and «Лучшее совпадение» marks only a fitting first card", async ({
  page,
}) => {
  const { amount_slider: config } = await catalogOf(page);
  const snapshot = await open(page);
  // At the default 2 000 000 ₽ both 23.50% unsecured products are within the 2 400 000 ₽ estimate (3 × 800 000 ₽).
  expect(config.default_rub).toBe(2000000);
  expect(annuity(2000000, 2350, 36)).toBe(77942);
  expect(lineInterest(2000000, 2350)).toBe(39167);
  await expect(page.locator(`${termCard} .product-payment`)).toContainText(
    grouped(annuity(2000000, 2350, 36), true),
  );
  await expect(page.locator(`${lineCard} .product-payment`)).toContainText(
    grouped(lineInterest(2000000, 2350), true),
  );

  // The tag sits on the server's first card because it fits, and on no other card.
  const tags = page.locator(".product-tag.best");
  expect(snapshot.items[0]).toMatchObject({
    product_id: "alfa_term_loan_unsecured",
    status: "fits",
  });
  await expect(tags).toHaveCount(1);
  await expect(tags).toHaveText("Лучшее совпадение");
  await expect(page.locator(termCard).locator(".product-tag.best")).toHaveCount(1);
  await expect(cards(page).first()).toHaveAttribute(
    "data-product-id",
    snapshot.items[0].product_id,
  );
  // 10 000 000 ₽ is above every personal estimate: the first card does not fit, so nothing is marked.
  const result = calculated(page);
  await amountField(page).fill("10000000");
  const above = (await (await result).json()) as { items: Item[] };
  expect(above.items[0].status).not.toBe("fits");
  await expect(cards(page).first()).toHaveAttribute(
    "data-product-id",
    above.items[0].product_id,
  );
  await expect(tags).toHaveCount(0);
});

test("amount slider: the track follows a typed amount, a preset and a key; arrows step from an off-grid amount; modifier keys stay the browser's; an unchanged amount is not recalculated", async ({
  page,
}) => {
  const { amount_slider: config } = await catalogOf(page);
  await open(page);
  const range = slider(page);
  const field = amountField(page);
  const steps = Number(await range.getAttribute("max"));
  const position = (amount: number) =>
    String(
      Math.round(
        (steps * Math.log(amount / config.min_rub)) /
          Math.log(config.max_rub / config.min_rub),
      ),
    );
  // Typed, preset and key amounts all move the track to their own position.
  await field.fill("1234567");
  await expect(range).toHaveValue(position(1234567));
  await expect(range).toHaveAttribute("aria-valuetext", grouped(1234567, true));
  // The arrows step from the typed amount to the grid's neighbours (100 000 ₽ steps in this band).
  await range.focus();
  await range.press("ArrowRight");
  await expect(field).toHaveValue(grouped(1300000));
  await expect(range).toHaveValue(position(1300000));
  await field.fill("1234567");
  await range.focus();
  await range.press("ArrowLeft");
  await expect(field).toHaveValue(grouped(1200000));
  await expect(range).toHaveValue(position(1200000));
  await page
    .getByRole("group", { name: "Быстрый выбор суммы" })
    .getByRole("button", { name: compact(30000000) })
    .click();
  await expect(field).toHaveValue(grouped(30000000));
  await expect(range).toHaveValue(position(30000000));

  // With Alt, Ctrl or Cmd held the arrows belong to the browser (history, word jumps): the amount stays.
  await range.focus();
  for (const keys of ["Alt+ArrowRight", "Control+ArrowRight", "Meta+ArrowRight"]) {
    await range.press(keys);
    await expect(field).toHaveValue(grouped(30000000));
    await expect(range).toHaveValue(position(30000000));
  }

  // An amount that is already shown is not calculated again: Home at the minimum, End at the maximum, the same preset.
  let posts = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/recommendations"))
      posts += 1;
  });
  const settled = async (amount: number) => {
    await expect(page.locator(".results-summary")).toContainText(
      "для суммы " + grouped(amount, true),
    );
    await expect(page.locator(".results-summary")).not.toContainText(
      "Пересчитываем",
    );
  };
  await range.press("Home");
  await settled(config.min_rub);
  const afterHome = posts;
  await range.press("Home");
  await range.press("ArrowLeft");
  await page.waitForTimeout(600);
  expect(posts).toBe(afterHome);
  await expect(cards(page).first()).toBeVisible();
  await range.press("End");
  await settled(config.max_rub);
  const afterEnd = posts;
  await range.press("End");
  await page.waitForTimeout(600);
  expect(posts).toBe(afterEnd);
  const preset = page
    .getByRole("group", { name: "Быстрый выбор суммы" })
    .getByRole("button", { name: compact(3000000) });
  await preset.click();
  await settled(3000000);
  const afterPreset = posts;
  await preset.click();
  await page.waitForTimeout(600);
  expect(posts).toBe(afterPreset);
  await expect(cards(page).first()).toBeVisible();

  // Digits beyond any safe number are still an amount: the field names the maximum, not a typing mistake.
  await field.fill("99999999999999999999");
  await expect(page.getByRole("alert")).toContainText(
    "Максимальная сумма — " + grouped(config.max_rub, true),
  );
  await expect(cards(page)).toHaveCount(0);
});

test("a failed calculation says so beside the error instead of «Пересчитываем…», and a retry recovers", async ({
  page,
}) => {
  await open(page);
  // One server failure, answered by the route; the retry reaches the real API.
  await page.route(
    `**/companies/${strong}/recommendations`,
    (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({
          error: {
            code: "INTERNAL_ERROR",
            message: "Не удалось выполнить запрос. Повторите попытку.",
          },
        }),
      }),
    { times: 1 },
  );
  await amountField(page).fill("1500000");
  await expect(page.getByRole("alert")).toContainText(
    "Не удалось выполнить запрос",
  );
  const summary = page.locator(".results-summary");
  await expect(summary).toContainText(
    "Не удалось рассчитать продукты для суммы " + grouped(1500000, true),
  );
  await expect(summary).not.toContainText("Пересчитываем");
  await page.getByRole("button", { name: "Повторить попытку" }).click();
  await expect(page.locator(termCard)).toContainText(
    "Расчёт на сумму " + grouped(1500000, true),
  );
  await expect(summary).toContainText("для суммы " + grouped(1500000, true));
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("a two-billion amount fits the field on a 390 px phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  const field = amountField(page);
  await field.fill("2000000000");
  await field.blur();
  await expect(field).toHaveValue(grouped(2000000000));
  // The whole number shows: nothing scrolls inside the field and the sign stays inside the card.
  expect(
    await field.evaluate(
      (element: HTMLInputElement) => element.scrollWidth <= element.clientWidth,
    ),
  ).toBe(true);
  const card = (await page.locator(".amount-picker").boundingBox())!;
  const sign = (await page.locator(".amount-value span").boundingBox())!;
  expect(sign.x + sign.width).toBeLessThanOrEqual(card.x + card.width);
  await expect(cards(page).first()).toBeVisible();
  await expectNoPageOverflow(page);
});

test("cards: two per row with aligned sections at 1366×768 and 1440, one column at 390 px, no horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  const snapshot = await open(page);
  const boxes = async () =>
    cards(page).evaluateAll((elements) =>
      elements.map((element) => {
        const box = element.getBoundingClientRect();
        const figures = element
          .querySelector(".product-figures")!
          .getBoundingClientRect();
        return {
          x: box.x,
          y: box.y,
          width: box.width,
          height: box.height,
          figures: figures.y,
        };
      }),
    );
  for (const width of [1366, 1440]) {
    await page.setViewportSize({ width, height: width === 1366 ? 768 : 1000 });
    await settle(page);
    const laid = await boxes();
    expect(laid).toHaveLength(snapshot.items.length);
    for (let index = 0; index + 1 < laid.length; index += 2) {
      const [left, right] = [laid[index], laid[index + 1]];
      // Two cards per row: same top, same height, side by side, the figures aligned across the row.
      expect(Math.abs(left.y - right.y)).toBeLessThan(1);
      expect(Math.abs(left.height - right.height)).toBeLessThan(1);
      expect(right.x).toBeGreaterThan(left.x + left.width);
      expect(Math.abs(left.figures - right.figures)).toBeLessThan(1);
      if (index + 2 < laid.length)
        expect(laid[index + 2].y).toBeGreaterThan(left.y + left.height);
    }
    await expectNoPageOverflow(page);
    await page.evaluate(() => window.scrollTo(0, 0));
    await settle(page);
    await page.screenshot({
      path: `${artifacts}/product-choice-${width}.png`,
      fullPage: true,
    });
  }
  await page
    .locator(termCard)
    .screenshot({ path: `${artifacts}/card.png` });

  // The switch sits at 900 px of window width: two columns there, one just below; nothing overflows either way.
  for (const [width, columns] of [
    [900, 2],
    [899, 1],
  ]) {
    await page.setViewportSize({ width, height: 900 });
    await settle(page);
    const [first, second] = await boxes();
    expect(Math.abs(first.y - second.y) < 1 ? 2 : 1).toBe(columns);
    await expectNoPageOverflow(page);
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await settle(page);
  const stacked = await boxes();
  for (const box of stacked.slice(1)) {
    expect(Math.abs(box.x - stacked[0].x)).toBeLessThan(1);
    expect(Math.abs(box.width - stacked[0].width)).toBeLessThan(1);
  }
  for (let index = 1; index < stacked.length; index += 1)
    expect(stacked[index].y).toBeGreaterThan(
      stacked[index - 1].y + stacked[index - 1].height,
    );
  await expectNoPageOverflow(page);
  // Keyboard reach on a phone: the slider still answers its keys.
  await slider(page).focus();
  await slider(page).press("Home");
  await expect(amountField(page)).toHaveValue(grouped(300000));
  await expect(page.locator(termCard)).toContainText(
    "Расчёт на сумму " + grouped(300000, true),
  );
  await page.evaluate(() => window.scrollTo(0, 0));
  await settle(page);
  await page.screenshot({
    path: `${artifacts}/product-choice-390.png`,
    fullPage: true,
  });
});

test("late calculation cannot overwrite the edited amount or navigate across company views", async ({
  page,
}) => {
  await open(page);
  let release!: () => void;
  let started!: () => void;
  const held = new Promise<void>((r) => (release = r));
  const pending = new Promise<void>((r) => (started = r));
  await page.route(`**/companies/${strong}/recommendations`, async (route) => {
    if (route.request().postDataJSON().requested_amount_rub !== 2500000) {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    started();
    await held;
    await route.fulfill({ response }).catch(() => {});
  });
  await amountField(page).fill("2500000");
  await pending;
  // While the held calculation runs the grid keeps its height: the page does not collapse under the reader.
  expect(
    (await page.locator("#product-grid").boundingBox())!.height,
  ).toBeGreaterThan(1000);
  await amountField(page).fill("1000000");
  await expect(page.locator(termCard)).toContainText(grouped(38971, true));
  release();
  await expect(amountField(page)).toHaveValue("1000000");
  await expect(page.locator(termCard)).toContainText(grouped(38971, true));
  await page.getByRole("button", { name: "Профиль компании" }).click();
  await expect(
    page.getByRole("heading", { name: "ООО «Сильный бизнес»" }),
  ).toBeVisible();
  await expect(cards(page)).toHaveCount(0);
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
  await expect(cards(page)).toHaveCount(
    (await catalogOf(page)).products.length,
  );
  for (const card of await cards(page).all()) {
    await expect(card).toContainText("Не соответствует параметрам");
    await expect(card).toContainText("Деятельность компании прекращена");
    await expect(card).toContainText("выберите действующую компанию");
    await expect(card).toContainText("Платёж не рассчитан");
    // No personal estimate for a company that does not operate.
    await expect(
      card.getByRole("group", { name: "Личная предварительная оценка" }),
    ).toContainText("Не рассчитывается");
    await expect(card).toContainText(
      "Анкету можно начать только для действующей компании.",
    );
  }
  await expect(page.getByText("Можно начать анкету")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Начать анкету" })).toHaveCount(
    0,
  );
  // Above the turnover-based figure the server still computes one (2 400 000 ₽ for 800 000 ₽ a month), but a closed
  // business gets neither an offer to recalculate at it nor a line about a smaller amount.
  await amountField(page).fill("3000000");
  await expect(page.locator(termCard)).toContainText(
    "Деятельность компании прекращена",
  );
  await expect(page.locator(".results-summary")).toContainText(
    "для суммы " + grouped(3000000, true),
  );
  await expect(page.getByRole("button", { name: /Рассчитать на/ })).toHaveCount(0);
  await expect(
    page.locator(".product-fit").filter({ hasText: "предварительной оценки" }),
  ).toHaveCount(0);
});

test("unavailable registry shows unknown eligibility and recovers after the retry", async ({
  page,
}) => {
  await onboardFixture(page, "Реестр недоступен");
  await expect(
    page.getByText("Статус компании в реестре не подтверждён"),
  ).toBeVisible();
  await expect(cards(page)).toHaveCount(
    (await catalogOf(page)).products.length,
  );
  await expect(page.locator(termCard)).toContainText("Нужны сведения");
  await expect(page.locator(termCard)).toContainText(grouped(2400000, true));
  await expect(page.getByText("Можно начать анкету")).toHaveCount(0);
  await expect(page.locator(termCard)).toContainText(
    "Повторите проверку реестра в профиле компании",
  );
  await page.getByRole("button", { name: "Профиль компании" }).click();
  await page.getByRole("button", { name: "Повторить проверку" }).click();
  await expect(
    page.getByText("Действующая компания", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await expect(page.locator(termCard)).toContainText(
    "Соответствует потребности",
  );
  await expect(page.locator(termCard)).toContainText("Можно начать анкету");
});

test("missing turnover keeps the cards, shows unknown estimates and asks for the data", async ({
  page,
}) => {
  await onboardFixture(page, "Неполные обороты");
  await expect(
    page.getByText("Нет положительных сведений об обороте"),
  ).toBeVisible();
  await expect(cards(page)).toHaveCount(
    (await catalogOf(page)).products.length,
  );
  // Every personal estimate is unknown; the term loan explains why and still allows a draft.
  for (const card of await cards(page).all())
    await expect(
      card.getByRole("group", { name: "Личная предварительная оценка" }),
    ).toContainText("Нужно уточнить");
  for (const text of [
    "Нужны сведения",
    "Платёж не рассчитан",
    "Можно начать анкету",
    "Оборот неизвестен",
  ])
    await expect(page.locator(termCard)).toContainText(text);
  await expect(page.locator(lineCard)).toContainText("бессрочно");
});
