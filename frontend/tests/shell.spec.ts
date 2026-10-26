import { expect, Locator } from "@playwright/test";
import { test } from "./fixtures";
import {
  expectStage,
  expectTouchTargets,
  loginClient,
  onboard,
  openRecommendations,
  registerClient,
  termCard,
} from "./helpers";

// The shell's accessibility details against the real app: the login heading on a phone, white text on the brand red,
// the keyboard focus ring, the breadcrumb separator, and the 44 px targets of the sidebar and of error notices. The
// seeded client is only read; the questionnaire's stepper belongs to a fresh synthetic client.

/** The channels of a computed `rgb(…)`/`rgba(…)` colour; alpha 1 when the value has none. */
function channels(value: string) {
  const [r, g, b, a = 1] = (value.match(/[\d.]+/g) ?? []).map(Number);
  return { r, g, b, a };
}

/** The WCAG 2 contrast ratio of two opaque computed colours. */
function contrast(first: string, second: string) {
  const luminance = (value: string) => {
    const linear = (channel: number) => {
      const s = channel / 255;
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    };
    const { r, g, b } = channels(value);
    return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
  };
  const [light, dark] = [luminance(first), luminance(second)].sort(
    (x, y) => y - x,
  );
  return (light + 0.05) / (dark + 0.05);
}

/** An element's text, background and outline colours, and the first opaque background behind it (where a ring sits). */
const colours = (locator: Locator) =>
  locator.evaluate((element) => {
    const style = getComputedStyle(element);
    let behind = "";
    for (let at = element.parentElement; at && !behind; at = at.parentElement) {
      const background = getComputedStyle(at).backgroundColor;
      if (Number(background.match(/[\d.]+/g)?.[3] ?? 1) === 1) behind = background;
    }
    return {
      text: style.color,
      background: style.backgroundColor,
      outline: style.outlineColor,
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      behind,
    };
  });

/** A focused control's ring: solid, 3 px, opaque, and at least 3:1 against what is behind it. */
async function expectVisibleRing(control: Locator) {
  await expect(control).toBeFocused();
  const ring = await colours(control);
  expect([ring.outlineStyle, ring.outlineWidth]).toEqual(["solid", "3px"]);
  expect(channels(ring.outline).a).toBe(1);
  expect(contrast(ring.outline, ring.behind)).toBeGreaterThanOrEqual(3);
}

test("on a phone the login heading keeps its words apart where its first line break is hidden", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const heading = page.getByRole("heading", { level: 1 });
  // What the screen shows and what assistive technology reads.
  expect((await heading.innerText()).replace(/\s+/g, " ")).toBe(
    "У вашего бизнеса есть планы. Начнём маршрут.",
  );
  await expect(heading).toHaveAccessibleName(
    /^У вашего бизнеса есть планы\.\s?Начнём маршрут\.$/,
  );
});

test("the sidebar's note keeps «ИП и ООО» together on one line at every sidebar width", async ({
  page,
}) => {
  await page.goto("/");
  await loginClient(page);
  // The sidebar is 245 px wide, 225 px from 1200 px down, and 245 px again in the phone menu.
  for (const width of [1440, 1100, 390]) {
    await page.setViewportSize({ width, height: 900 });
    const tops = await page.locator(".sidebar-note").evaluate((note) => {
      const text = [...note.childNodes].find((node) =>
        node.textContent?.includes("ООО"),
      )!;
      const top = (word: string) => {
        const range = document.createRange();
        const start = text.textContent!.indexOf(word);
        range.setStart(text, start);
        range.setEnd(text, start + word.length);
        return Math.round(range.getBoundingClientRect().top);
      };
      return [top("ИП"), top("ООО")];
    });
    expect(tops[1], `${width} px`).toBe(tops[0]);
  }
});

test("white text on the brand red reads at 4.5:1, darker on hover, and every keyboard focus ring is opaque at 3:1", async ({
  page,
}) => {
  await page.goto("/");
  const submit = page.getByRole("button", { name: "Войти в кабинет" });
  const button = await colours(submit);
  expect(contrast(button.text, button.background)).toBeGreaterThanOrEqual(4.5);
  // Hovered, it turns darker still (polled: the background eases over 0.15 s).
  await submit.hover();
  await expect
    .poll(async () => {
      const hovered = await colours(submit);
      return contrast(hovered.text, hovered.background);
    })
    .toBeGreaterThan(contrast(button.text, button.background));
  await page.mouse.move(0, 0);

  // The ring on the light login page, reached with the keyboard.
  await page.getByLabel("Пароль", { exact: true }).focus();
  await page.keyboard.press("Tab");
  await expectVisibleRing(submit);

  // The ring on the dark sidebar.
  await loginClient(page);
  const nav = page.locator(".sidebar nav button");
  await nav.nth(1).focus();
  await page.keyboard.press("Shift+Tab");
  await expectVisibleRing(nav.first());

  // Every focus ring the loaded stylesheets declare, the features' included, is opaque.
  const rings = await page.evaluate(() => {
    const rules: CSSStyleRule[] = [];
    const collect = (list: CSSRuleList) => {
      for (const rule of list)
        if (rule instanceof CSSStyleRule) rules.push(rule);
        else if (rule instanceof CSSGroupingRule) collect(rule.cssRules);
    };
    for (const sheet of document.styleSheets) collect(sheet.cssRules);
    const probe = document.body.appendChild(document.createElement("div"));
    const found = rules
      .filter(
        (rule) =>
          rule.selectorText.includes(":focus") &&
          !["", "none"].includes(rule.style.getPropertyValue("outline")),
      )
      .map((rule) => {
        probe.style.outline = rule.style.getPropertyValue("outline");
        return `${rule.selectorText} → ${getComputedStyle(probe).outlineColor}`;
      });
    probe.remove();
    return found;
  });
  // The stylesheets were really read (the app's own rings, the questionnaire's, the documents', the officer's…).
  expect(rings.length).toBeGreaterThan(5);
  expect(rings.filter((ring) => ring.includes("rgba("))).toEqual([]);
});

test("the questionnaire's current stage number is white on a red that reads at 4.5:1", async ({
  page,
}) => {
  await registerClient(page, "shell-stepper");
  await onboard(page, "Сильный бизнес");
  await openRecommendations(page);
  await page
    .locator(termCard)
    .getByRole("button", { name: "Начать анкету" })
    .click();
  await expectStage(page, 1, "Компания");
  const mark = page.locator(".stepper .current .step-mark");
  await expect(mark).toHaveText("1");
  const { text, background } = await colours(mark);
  expect(contrast(text, background)).toBeGreaterThanOrEqual(4.5);
});

test("the breadcrumb's slash is decoration: assistive technology reads only the places", async ({
  page,
}) => {
  await page.goto("/");
  await loginClient(page);
  const crumbs = page.locator(".breadcrumbs");
  await expect(crumbs).toContainText("Мои компании");
  const read = await crumbs.ariaSnapshot();
  expect(read).toContain("Бизнес");
  expect(read).toContain("Мои компании");
  expect(read).not.toContain("/");
});

test("the sidebar's logout and the «Повторить попытку» of a failed page or start are 44 px targets", async ({
  page,
}) => {
  await page.goto("/");
  await loginClient(page);
  const logout = await page
    .getByRole("button", { name: "Выйти из аккаунта" })
    .boundingBox();
  expect(logout!.width).toBeGreaterThanOrEqual(44);
  expect(logout!.height).toBeGreaterThanOrEqual(44);
  // A page whose data did not arrive: the notice's retry beside the sidebar.
  await page.route("**/api/v1/companies", (route) => route.abort());
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Повторить попытку" }),
  ).toBeVisible();
  await expectTouchTargets(page);
  await page.unroute("**/api/v1/companies");
  // A start that could not check the session: the same notice on its own.
  await page.route("**/api/v1/auth/me", (route) => route.abort());
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Повторить попытку" }),
  ).toBeVisible();
  await expect(page.locator(".sidebar")).toHaveCount(0);
  await expectTouchTargets(page);
  await page.unroute("**/api/v1/auth/me");
  await page.getByRole("button", { name: "Повторить попытку" }).click();
  await expect(page.getByLabel("Ваша компания", { exact: true })).toBeVisible();
});
