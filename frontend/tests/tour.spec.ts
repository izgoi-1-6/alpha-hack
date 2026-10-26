import { expect, Locator, Page } from "@playwright/test";
import { test } from "./fixtures";
import {
  authorityDialog,
  expectNoDemoWording,
  expectNoPageOverflow,
  expectStage,
  loginOfficer,
  onboard,
  password,
  registerClient,
  revision,
  settle,
} from "./helpers";

// The interactive client walkthrough (Task 12): it opens by itself on a new client's first visit and leads from adding
// a company to the questionnaire; the client acts on the real pages and a new page brings the next step. It can be
// skipped, it is restarted from «Как это работает», and an officer never sees it. Every other spec runs with it off
// (fixtures.ts); this one switches it on. Real UI and API throughout, fresh synthetic clients only.

test.use({ tour: true });

const TOTAL = 9;
const KEY = "credit-route.tour.v1.";
/** The `data-tour` anchors each step highlights. */
const ANCHORS: Record<number, string[]> = {
  1: ["add-company"],
  2: ["choose-company"],
  3: ["gosuslugi"],
  4: ["consents"],
  5: ["find-financing"],
  6: ["amount-field", "amount-slider"],
  7: ["product-head", "product-explanation"],
  8: ["start-application"],
  9: ["questionnaire"],
};

const walkthrough = (page: Page) =>
  page.getByRole("dialog", { name: /^Шаг \d+ из 9/ });
const tourButton = (page: Page, name: string) =>
  walkthrough(page).getByRole("button", { name, exact: true });
const howItWorks = (page: Page) =>
  page.locator("header").getByRole("button", { name: "Как это работает" });
const sidebar = (page: Page, name: string) =>
  page.locator(".sidebar").getByRole("button", { name });

async function userId(page: Page): Promise<string> {
  const response = await page.request.get("/api/v1/auth/me");
  expect(response.status()).toBe(200);
  return (await response.json()).user.id;
}
const storage = (page: Page) =>
  page.evaluate(() => Object.entries(window.localStorage));

/**
 * What is wrong with the open step's layout, measured over two frames (a layout still moving counts as a problem):
 * every anchor is fully in view and hit-testable at its centre and inner corners, so nothing — the popover, the
 * sticky top bar, the bottom sheet — covers or blocks it; the popover does not intersect it, stays inside the
 * viewport and above the top bar (z-index 40) and the sidebar (30), and is a bottom sheet below 760 px; the
 * spotlight surrounds the anchors.
 */
function layoutProblems(page: Page, names: string[]) {
  return page.evaluate(async (anchorNames) => {
    const frames = () =>
      new Promise((done) =>
        requestAnimationFrame(() => requestAnimationFrame(done)),
      );
    const popover = document.querySelector<HTMLElement>(
      '[role="dialog"][aria-modal="false"]',
    );
    const spotlight = document.querySelector<HTMLElement>(".tour-spotlight");
    if (!popover || !spotlight) return ["no walkthrough on screen"];
    const where = () =>
      JSON.stringify([
        popover.getBoundingClientRect(),
        spotlight.getBoundingClientRect(),
        scrollY,
      ]);
    const before = where();
    await frames();
    if (where() !== before) return ["still moving"];
    const problems: string[] = [];
    const box = popover.getBoundingClientRect();
    if (
      box.left < 0 ||
      box.top < 0 ||
      box.right > innerWidth + 0.5 ||
      box.bottom > innerHeight + 0.5
    )
      problems.push("popover outside the viewport");
    for (const [name, element] of [
      ["popover", popover],
      ["spotlight", spotlight],
    ] as const)
      if (!(Number(getComputedStyle(element).zIndex) > 40))
        problems.push(`${name} not above the top bar and the sidebar`);
    if (
      innerWidth <= 760 &&
      (box.left !== 0 ||
        Math.abs(box.right - innerWidth) > 0.5 ||
        Math.abs(box.bottom - innerHeight) > 0.5)
    )
      problems.push("not a bottom sheet");
    const light = spotlight.getBoundingClientRect();
    for (const name of anchorNames) {
      const anchor = document.querySelector(`[data-tour="${name}"]`);
      if (!anchor) {
        problems.push(`${name}: missing`);
        continue;
      }
      const r = anchor.getBoundingClientRect();
      if (
        r.left < box.right &&
        box.left < r.right &&
        r.top < box.bottom &&
        box.top < r.bottom
      )
        problems.push(`${name}: covered by the popover`);
      if (
        r.left < light.left - 0.5 ||
        r.top < light.top - 0.5 ||
        r.right > light.right + 0.5 ||
        r.bottom > light.bottom + 0.5
      )
        problems.push(`${name}: outside the spotlight`);
      const inset = Math.min(14, r.width / 4, r.height / 4);
      const points = [
        [r.left + r.width / 2, r.top + r.height / 2],
        [r.left + inset, r.top + inset],
        [r.right - inset, r.top + inset],
        [r.left + inset, r.bottom - inset],
        [r.right - inset, r.bottom - inset],
      ];
      for (const [x, y] of points) {
        const hit = document.elementFromPoint(x, y);
        if (!hit || !anchor.contains(hit)) {
          problems.push(
            `${name}: ${hit ? `${hit.tagName}.${hit.className}` : "out of view"} at ${Math.round(x)},${Math.round(y)}`,
          );
          break;
        }
      }
    }
    return problems;
  }, names);
}

/** The walkthrough shows step `number` («Шаг N из 9») on its anchors, laid out as `layoutProblems` requires. */
async function expectStep(page: Page, number: number) {
  const dialog = walkthrough(page);
  await expect(dialog).toHaveAccessibleName(
    new RegExp(`^Шаг ${number} из ${TOTAL}(\\s|$)`),
  );
  await expect(dialog).toContainText(`Шаг ${number} из ${TOTAL}`);
  await expect
    .poll(() => layoutProblems(page, ANCHORS[number]), { timeout: 15_000 })
    .toEqual([]);
  await expectNoPageOverflow(page);
}

async function expectVisibleFocus(control: Locator) {
  await expect(control).toBeFocused();
  const outline = await control.evaluate((element) => {
    const style = getComputedStyle(element);
    return { style: style.outlineStyle, width: parseFloat(style.outlineWidth) };
  });
  expect(outline.style).not.toBe("none");
  expect(outline.width).toBeGreaterThanOrEqual(2);
}

/** Every walkthrough button is a 44 px target. */
async function expectTourTargets(page: Page) {
  for (const button of await walkthrough(page).getByRole("button").all()) {
    const box = (await button.boundingBox())!;
    expect(box.height).toBeGreaterThanOrEqual(44);
    expect(box.width).toBeGreaterThanOrEqual(44);
  }
}

/** Records the `behavior` of every page scroll the app asks for (the walkthrough brings each anchor into view). */
async function recordScrolls(page: Page) {
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as { scrolls: string[] }).scrolls = seen;
    for (const name of ["scrollTo", "scrollBy"] as const) {
      const original = window[name].bind(window) as (
        ...args: unknown[]
      ) => void;
      (window as unknown as Record<string, unknown>)[name] = (
        ...args: unknown[]
      ) => {
        const options = args[0];
        seen.push(
          typeof options === "object" && options !== null
            ? ((options as ScrollToOptions).behavior ?? "auto")
            : "auto",
        );
        original(...args);
      };
    }
  });
}
const scrolls = (page: Page) =>
  page.evaluate(() => (window as unknown as { scrolls: string[] }).scrolls);

/**
 * The full walk of a new client, from the empty home to the questionnaire: the client acts on the highlighted
 * controls (adding the company, the Госуслуги check, the consents, the product choice) and uses «Далее» and
 * «Назад» within a page. Reaching the last step completes the walkthrough: on the desktop the client closes it with
 * «Готово», on the phone by leaving the questionnaire. Captures the steps for the report.
 */
async function walk(page: Page, size: "desktop" | "mobile") {
  const shot = (name: string) =>
    page.screenshot({ path: `${revision}/task-12-${size}-${name}.png` });
  const id = await userId(page);

  await expectStep(page, 1);
  await expect(walkthrough(page)).toBeFocused();
  await expect(walkthrough(page)).toContainText("Нажмите «Добавить компанию»");
  await expect(tourButton(page, "Далее")).toHaveCount(0);
  await expect(tourButton(page, "Назад")).toHaveCount(0);
  await expectTourTargets(page);
  await expectNoDemoWording(page);
  if (size === "desktop") await shot("step-1");
  // The highlighted control stays clickable through the spotlight; the new page brings the next step.
  await page.locator('[data-tour="add-company"]').click();

  await expectStep(page, 2);
  await expect(tourButton(page, "Далее")).toBeFocused();
  await expectNoDemoWording(page);
  if (size === "mobile") await shot("step-2");
  await page.getByRole("button").filter({ hasText: "Сильный бизнес" }).click();
  await tourButton(page, "Далее").click();

  await expectStep(page, 3);
  await expectNoDemoWording(page);
  // The page's own modal dialog takes over: the walkthrough steps aside and comes back when it closes, leaving focus
  // where the dialog returns it.
  await page
    .getByRole("button", { name: "Подтвердить через Госуслуги" })
    .click();
  const dialog = authorityDialog(page);
  await expect(
    dialog.getByRole("button", { name: "Подтвердить" }),
  ).toBeFocused();
  await expect(walkthrough(page)).toHaveCount(0);
  await expect(page.locator(".tour-spotlight")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Подтвердить" }).click();
  await expect(dialog).toHaveCount(0);
  await expectStep(page, 3);
  await expect(page.getByRole("status")).toBeFocused();
  await tourButton(page, "Далее").click();

  await expectStep(page, 4);
  await expect(walkthrough(page)).toContainText(
    "Затем нажмите «Добавить и проверить»",
  );
  await expectTourTargets(page);
  await expectNoDemoWording(page);
  if (size === "desktop") await shot("step-4");
  await tourButton(page, "Назад").click();
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
  await expect(tourButton(page, "Назад")).toHaveCount(0);
  await expectNoDemoWording(page);
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();

  await expectStep(page, 6);
  await expectNoDemoWording(page);
  if (size === "mobile") await shot("step-6");
  await tourButton(page, "Далее").click();

  await expectStep(page, 7);
  await expectNoDemoWording(page);
  if (size === "desktop") await shot("step-7");
  await tourButton(page, "Далее").click();

  await expectStep(page, 8);
  await expectNoDemoWording(page);
  await page.locator('[data-tour="start-application"]').first().click();

  await expectStage(page, 1, "Компания");
  await expectStep(page, 9);
  await expect(tourButton(page, "Готово")).toBeFocused();
  await expect(tourButton(page, "Пропустить")).toHaveCount(0);
  await expectTourTargets(page);
  await expectNoDemoWording(page);
  await shot("step-9");
  // The only thing the walkthrough keeps in the browser is its own flag, set once the last step is reached.
  expect(await storage(page)).toEqual([[KEY + id, "done"]]);
  if (size === "desktop") {
    await tourButton(page, "Готово").click();
    await expect(walkthrough(page)).toHaveCount(0);
    await expect(howItWorks(page)).toBeFocused();
    return;
  }
  // Leaving the questionnaire closes it; coming back to the draft does not reopen it.
  await page.getByRole("button", { name: "← Мои заявки" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Мои заявки" }),
  ).toBeVisible();
  await expect(walkthrough(page)).toHaveCount(0);
  await page.goBack();
  await expectStage(page, 1, "Компания");
  await settle(page);
  await expect(walkthrough(page)).toHaveCount(0);
  expect(await storage(page)).toEqual([[KEY + id, "done"]]);
}

test("a new client is walked from the first login to the questionnaire on a 1440×1000 screen and is not walked again", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await recordScrolls(page);
  await registerClient(page, "tour-desktop");
  await walk(page, "desktop");
  expect(await scrolls(page)).toContain("smooth");
  // Completed: a reload of the questionnaire does not bring it back.
  await page.reload();
  await expectStage(page, 1, "Компания");
  await settle(page);
  await expect(walkthrough(page)).toHaveCount(0);
});

test("on a 390×844 phone the walkthrough is a bottom sheet over the page and follows the reduced-motion setting", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await recordScrolls(page);
  await registerClient(page, "tour-mobile");
  await expectStep(page, 1);
  expect(
    await walkthrough(page).evaluate((element) =>
      parseFloat(getComputedStyle(element).animationDuration),
    ),
  ).toBeLessThan(0.001);
  await walk(page, "mobile");
  const behaviors = await scrolls(page);
  expect(behaviors.length).toBeGreaterThan(0);
  expect(behaviors).not.toContain("smooth");
});

test("«Пропустить» and Escape skip the walkthrough; it stays closed after a reload", async ({
  page,
}) => {
  await registerClient(page, "tour-skip");
  const id = await userId(page);
  await expectStep(page, 1);
  await tourButton(page, "Пропустить").click();
  await expect(walkthrough(page)).toHaveCount(0);
  await expect(howItWorks(page)).toBeFocused();
  expect(await storage(page)).toEqual([[KEY + id, "skipped"]]);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Здесь появятся ваши компании" }),
  ).toBeVisible();
  await settle(page);
  await expect(walkthrough(page)).toHaveCount(0);

  await sidebar(page, "Добавить компанию").click();
  await howItWorks(page).click();
  await expectStep(page, 2);
  await page.keyboard.press("Escape");
  await expect(walkthrough(page)).toHaveCount(0);
  await expect(howItWorks(page)).toBeFocused();
  expect(await storage(page)).toEqual([[KEY + id, "skipped"]]);
});

test("«Как это работает» restarts the walkthrough on the current page from its first step there, or from «Мои компании» on a page without steps", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await registerClient(page, "tour-restart");
  await expectStep(page, 1);
  await tourButton(page, "Пропустить").click();
  await onboard(page, "Сильный бизнес");

  // The company profile has no anchor of steps 1–4: the walkthrough starts at step 5.
  await howItWorks(page).click();
  await expectStep(page, 5);
  await expect(tourButton(page, "Назад")).toHaveCount(0);
  await tourButton(page, "Пропустить").click();

  // «Мои заявки» shows no step: the walkthrough opens on «Мои компании».
  await sidebar(page, "Мои заявки").click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Мои заявки" }),
  ).toBeVisible();
  await howItWorks(page).click();
  await expect(
    page.getByRole("heading", { name: "Что удалось узнать" }),
  ).toBeVisible();
  await expectStep(page, 5);
  await tourButton(page, "Пропустить").click();

  // A restart while the page is still loading waits for it: on the onboarding page it starts at step 2.
  let release!: () => void;
  const held = new Promise<void>((done) => (release = done));
  await page.route(/\/consents\/documents\?stage=onboarding/, async (route) => {
    await held;
    await route.continue();
  });
  await sidebar(page, "Добавить компанию").click();
  await expect(page.locator("main .loading")).toBeVisible();
  await howItWorks(page).click();
  release();
  await expect(
    page.getByRole("heading", { level: 1, name: "Начнём с вашего бизнеса" }),
  ).toBeVisible();
  await expectStep(page, 2);
  await expect(tourButton(page, "Далее")).toBeFocused();
});

test("a step whose anchor is absent is skipped: an inactive company offers no «Начать анкету», so step 8 is passed over", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await registerClient(page, "tour-absent");
  await expectStep(page, 1);
  await tourButton(page, "Пропустить").click();
  await onboard(page, "Неактивный бизнес");
  await howItWorks(page).click();
  await expectStep(page, 5);
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await expectStep(page, 6);
  await tourButton(page, "Далее").click();
  await expectStep(page, 7);
  await expect(page.locator('[data-tour="start-application"]')).toHaveCount(0);
  await tourButton(page, "Далее").click();
  // Nothing after step 7 can be shown on this page: the walkthrough steps aside until a questionnaire opens.
  await expect(walkthrough(page)).toHaveCount(0);
  await expect(page.locator(".product-card").first()).toContainText(
    "Анкету можно начать только для действующей компании.",
  );
  await howItWorks(page).click();
  await expectStep(page, 6);
});

test("«Далее» before the products are calculated: the walkthrough waits on «Как это работает», then brings step 7 into view with focus", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await registerClient(page, "tour-wait");
  await expectStep(page, 1);
  await tourButton(page, "Пропустить").click();
  await onboard(page, "Сильный бизнес");
  let release!: () => void;
  let started!: () => void;
  const held = new Promise<void>((done) => (release = done));
  const calculating = new Promise<void>((done) => (started = done));
  await page.route("**/companies/*/recommendations", async (route) => {
    const response = await route.fetch();
    started();
    await held;
    await route.fulfill({ response }).catch(() => {});
  });
  await page.getByRole("button", { name: "Подобрать финансирование" }).click();
  await calculating;
  await howItWorks(page).click();
  await expectStep(page, 6);
  await tourButton(page, "Далее").click();
  await expect(walkthrough(page)).toHaveCount(0);
  await expect(howItWorks(page)).toBeFocused();
  release();
  await expectStep(page, 7);
  await expect(tourButton(page, "Далее")).toBeFocused();
});

test("an officer never sees the walkthrough or «Как это работает»", async ({
  page,
}) => {
  await page.goto("/");
  await loginOfficer(page);
  await settle(page);
  await expect(walkthrough(page)).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Как это работает" }),
  ).toHaveCount(0);
  expect((await storage(page)).filter(([key]) => key.startsWith(KEY))).toEqual(
    [],
  );
});

test("keyboard only: focus enters each step, Tab reaches the highlighted control and Shift+Tab returns, Enter acts, Escape skips and focus goes back to «Как это работает»", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await registerClient(page, "tour-keyboard");
  await expectStep(page, 1);
  await expect(walkthrough(page)).toBeFocused();
  await page.keyboard.press("Tab");
  await expectVisibleFocus(tourButton(page, "Пропустить"));
  const add = page.locator('[data-tour="add-company"]');
  await page.keyboard.press("Tab");
  await expect(add).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(tourButton(page, "Пропустить")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(add).toBeFocused();
  await page.keyboard.press("Enter");

  await expectStep(page, 2);
  await expectVisibleFocus(tourButton(page, "Далее"));
  await page.keyboard.press("Tab");
  const first = page
    .locator('[data-tour="choose-company"]')
    .getByRole("button")
    .first();
  await expect(first).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(first).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Shift+Tab");
  await expect(tourButton(page, "Далее")).toBeFocused();
  await page.keyboard.press("Enter");

  await expectStep(page, 3);
  await expect(tourButton(page, "Далее")).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expectVisibleFocus(tourButton(page, "Назад"));
  await page.keyboard.press("Enter");
  await expectStep(page, 2);
  await expect(tourButton(page, "Далее")).toBeFocused();
  await page.keyboard.press("Enter");
  await expectStep(page, 3);
  await page.keyboard.press("Enter");

  await expectStep(page, 4);
  await expect(walkthrough(page)).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(walkthrough(page)).toHaveCount(0);
  await expect(howItWorks(page)).toBeFocused();
  await page.keyboard.press("Enter");
  await expectStep(page, 2);
  await expect(tourButton(page, "Далее")).toBeFocused();
});

test("without browser storage the walkthrough opens once per page session and nothing breaks", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new DOMException("Storage is disabled", "SecurityError");
      },
    });
  });
  const email = await registerClient(page, "tour-storage");
  await expectStep(page, 1);
  await tourButton(page, "Пропустить").click();
  await expect(walkthrough(page)).toHaveCount(0);
  // Remembered in memory while the page lives: across its pages, and across a new sign-in of the same client.
  await sidebar(page, "Мои заявки").click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Мои заявки" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Выйти из аккаунта" }).click();
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти в кабинет" }).click();
  await expect(
    page.getByRole("heading", { name: "Здесь появятся ваши компании" }),
  ).toBeVisible();
  await settle(page);
  await expect(walkthrough(page)).toHaveCount(0);
  // A reload is a new page session: the walkthrough opens once more.
  await page.reload();
  await expectStep(page, 1);
  expect(errors).toEqual([]);
});
