import { expect } from "@playwright/test";
import { test } from "./fixtures";
import {
  artifacts,
  authorityDialog,
  confirmAuthority,
  loginClient,
  onboard,
  password,
  registerClient,
  revision,
  settle,
} from "./helpers";

test("seeded client login, source details, retry and persistent refresh", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "С возвращением" }),
  ).toBeVisible();
  // Quick login keeps its three profiles; the seed password is never shown as copy on the page.
  for (const name of [
    "Войти как клиент",
    "Войти как специалист",
    "Новый клиент",
  ])
    await expect(page.getByRole("button", { name, exact: true })).toBeVisible();
  await expect(page.locator("body")).not.toContainText(password);
  await expect(page.locator("body")).not.toContainText("Пароль:");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: artifacts + "/task-2-login-desktop.png",
    fullPage: true,
  });
  await page.screenshot({
    path: `${revision}/task-11-login.png`,
    fullPage: true,
  });
  await loginClient(page);
  await page
    .getByLabel("Ваша компания", { exact: true })
    .selectOption({ label: "ООО «Сильный бизнес» · 9900000017" });
  await expect(
    page.getByRole("heading", { name: "ООО «Сильный бизнес»" }),
  ).toBeVisible();
  await expect(page.getByText("800 000 ₽", { exact: true })).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: artifacts + "/task-2-company-desktop.png",
    fullPage: true,
  });
  expect(await page.evaluate(() => document.cookie)).not.toContain(
    "credit_route_session",
  );
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "ООО «Сильный бизнес»" }),
  ).toBeVisible();
  await page
    .getByLabel("Ваша компания", { exact: true })
    .selectOption({ label: "ООО «Неактивный бизнес» · 9900000049" });
  await expect(
    page.getByText("Компания доступна только для просмотра"),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Добавить компанию", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Начнём с вашего бизнеса" }),
  ).toBeVisible();
  await page
    .getByRole("button")
    .filter({ hasText: "Реестр недоступен" })
    .click();
  await expect(page.getByLabel("ИНН компании или ИП")).toHaveValue(
    "9900000063",
  );
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: artifacts + "/task-2-onboarding-desktop.png",
    fullPage: true,
  });
});

test("mobile registration, explicit consents, source recovery, reload, errors and logout", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Регистрация", exact: true }).click();
  await page.getByLabel("Ваше имя").fill("Пётр Предприниматель");
  await page
    .getByLabel("Электронная почта")
    .fill(`browser-${Date.now()}@example.test`);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page
    .getByRole("button", { name: "Создать аккаунт", exact: true })
    .click();
  await page
    .getByRole("main")
    .getByRole("button", { name: "Добавить компанию", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Добавить и проверить" }),
  ).toBeDisabled();
  await page
    .getByRole("button")
    .filter({ hasText: "Реестр недоступен" })
    .click();
  for (const checkbox of await page.getByRole("checkbox").all())
    await checkbox.check();
  // Adding a company needs the representative's Госуслуги confirmation for this ИНН.
  await expect(
    page.getByRole("button", { name: "Добавить и проверить" }),
  ).toBeDisabled();
  await confirmAuthority(page);
  await expect(page.getByRole("status")).toContainText(
    "Фёдоров Денис Алексеевич",
  );
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: artifacts + "/task-2-onboarding-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Добавить и проверить" }).click();
  await expect(
    page.getByText("Реестр временно недоступен", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("Реестр временно недоступен", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Повторить проверку" }).click();
  await expect(
    page.getByText("Действующая компания", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("Действующая компания", { exact: true }),
  ).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: artifacts + "/task-2-company-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.route("**/api/v1/companies", (route) => route.abort());
  await page.reload();
  await expect(page.getByRole("alert")).toContainText("Нет связи с сервером");
  await page.unroute("**/api/v1/companies");
  await page.getByRole("button", { name: "Повторить попытку" }).click();
  await expect(
    page.getByText("Действующая компания", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Открыть меню" }).click();
  await page.getByRole("button", { name: "Выйти из аккаунта" }).click();
  await expect(
    page.getByRole("heading", { name: "С возвращением" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "С возвращением" }),
  ).toBeVisible();
});

for (const outcome of ["success", "unauthorized"] as const) {
  test(`delayed retry ${outcome} for A cannot replace B or clear B's pending command`, async ({
    page,
  }) => {
    await page.goto("/");
    await loginClient(page);
    const companyA = "e230a446-129b-570f-b450-3cd8f7ddc8e5";
    await page
      .getByLabel("Ваша компания", { exact: true })
      .selectOption(companyA);
    await expect(
      page.getByRole("heading", { name: "ООО «Сильный бизнес»" }),
    ).toBeVisible();
    let releaseA!: () => void;
    let startedA!: () => void;
    let deliveredA!: () => void;
    const heldA = new Promise<void>((resolve) => (releaseA = resolve));
    const pendingA = new Promise<void>((resolve) => (startedA = resolve));
    const completedA = new Promise<void>((resolve) => (deliveredA = resolve));
    await page.route(
      `**/companies/${companyA}/precheck/retry`,
      async (route) => {
        const response = await route.fetch();
        startedA();
        await heldA;
        if (outcome === "success") await route.fulfill({ response });
        else
          await route.fulfill({
            status: 401,
            json: {
              error: {
                code: "AUTH_REQUIRED",
                message: "Войдите в свой аккаунт",
              },
            },
          });
        deliveredA();
      },
    );
    await page.getByRole("button", { name: "Повторить проверку" }).click();
    await pendingA;
    await page
      .getByLabel("Ваша компания", { exact: true })
      .selectOption({ label: "ООО «Неактивный бизнес» · 9900000049" });
    await expect(
      page.getByRole("heading", { name: "ООО «Неактивный бизнес»" }),
    ).toBeVisible();
    const selectedUrl = page.url();
    const companyB = await page
      .getByLabel("Ваша компания", { exact: true })
      .inputValue();
    let releaseB!: () => void;
    let startedB!: () => void;
    let deliveredB!: () => void;
    const heldB = new Promise<void>((resolve) => (releaseB = resolve));
    const pendingB = new Promise<void>((resolve) => (startedB = resolve));
    const completedB = new Promise<void>((resolve) => (deliveredB = resolve));
    await page.route(
      `**/companies/${companyB}/precheck/retry`,
      async (route) => {
        const response = await route.fetch();
        startedB();
        await heldB;
        await route.fulfill({ response });
        deliveredB();
      },
    );
    await page.getByRole("button", { name: "Повторить проверку" }).click();
    await pendingB;
    try {
      releaseA();
      await completedA;
      await settle(page);
      await expect(
        page.getByRole("heading", { name: "ООО «Неактивный бизнес»" }),
      ).toBeVisible();
      expect(page.url()).toBe(selectedUrl);
      await expect(
        page.getByRole("button", { name: "Обновляем…" }),
      ).toBeDisabled();
      await expect(
        page.getByLabel("Ваша компания", { exact: true }),
      ).toHaveValue(companyB);
    } finally {
      releaseB();
    }
    await completedB;
    await expect(
      page.getByRole("button", { name: "Повторить проверку" }),
    ).toBeEnabled();
  });
}

for (const outcome of ["success", "unauthorized"] as const) {
  test(`delayed prior-session workspace ${outcome} cannot overwrite a new login`, async ({
    page,
  }) => {
    await page.goto("/");
    await loginClient(page);
    await expect(
      page.getByLabel("Ваша компания", { exact: true }),
    ).toBeVisible();
    const companyA = "e230a446-129b-570f-b450-3cd8f7ddc8e5";
    let release!: () => void;
    let started!: () => void;
    let delivered!: () => void;
    const held = new Promise<void>((resolve) => (release = resolve));
    const pending = new Promise<void>((resolve) => (started = resolve));
    const completed = new Promise<void>((resolve) => (delivered = resolve));
    await page.route(`**/companies/${companyA}`, async (route) => {
      const response = await route.fetch();
      started();
      await held;
      try {
        if (outcome === "success") await route.fulfill({ response });
        else
          await route.fulfill({
            status: 401,
            json: {
              error: {
                code: "AUTH_REQUIRED",
                message: "Войдите в свой аккаунт",
              },
            },
          });
      } finally {
        delivered();
      }
    });
    await page
      .getByLabel("Ваша компания", { exact: true })
      .selectOption(companyA);
    await pending;
    await page.getByRole("button", { name: "Выйти из аккаунта" }).click();
    await expect(
      page.getByRole("heading", { name: "С возвращением" }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Новый клиент", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Здесь появятся ваши компании" }),
    ).toBeVisible();
    release();
    await completed;
    await settle(page);
    await expect(
      page.getByRole("heading", { name: "Здесь появятся ваши компании" }),
    ).toBeVisible();
    await expect(
      page.getByText("other@demo.local", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "ООО «Сильный бизнес»" }),
    ).toHaveCount(0);
  });
}

test("company retry retains its replay body and key after navigation and a lost response", async ({
  page,
}) => {
  await page.goto("/");
  await loginClient(page);
  const companyA = "e230a446-129b-570f-b450-3cd8f7ddc8e5";
  await page
    .getByLabel("Ваша компания", { exact: true })
    .selectOption(companyA);
  await expect(
    page.getByRole("heading", { name: "ООО «Сильный бизнес»" }),
  ).toBeVisible();
  let release!: () => void;
  let started!: () => void;
  let delivered!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  const pending = new Promise<void>((resolve) => (started = resolve));
  const completed = new Promise<void>((resolve) => (delivered = resolve));
  const commands: {
    key: string | undefined;
    body: unknown;
    resultVersion: number;
  }[] = [];
  await page.route(`**/companies/${companyA}/precheck/retry`, async (route) => {
    const response = await route.fetch();
    const result = await response.json();
    commands.push({
      key: route.request().headers()["idempotency-key"],
      body: route.request().postDataJSON(),
      resultVersion: result.company.version,
    });
    if (commands.length === 1) {
      started();
      await held;
      await route.abort();
      delivered();
    } else await route.fulfill({ response });
  });
  await page.getByRole("button", { name: "Повторить проверку" }).click();
  await pending;
  await page
    .getByLabel("Ваша компания", { exact: true })
    .selectOption({ label: "ООО «Неактивный бизнес» · 9900000049" });
  await expect(
    page.getByRole("heading", { name: "ООО «Неактивный бизнес»" }),
  ).toBeVisible();
  release();
  await completed;
  await settle(page);
  await page
    .getByLabel("Ваша компания", { exact: true })
    .selectOption(companyA);
  await expect(
    page.getByRole("heading", { name: "ООО «Сильный бизнес»" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Повторить проверку" }).click();
  await expect(
    page.getByRole("button", { name: "Повторить проверку" }),
  ).toBeEnabled();
  expect(commands).toHaveLength(2);
  expect(commands[1]).toEqual(commands[0]);
});

test("history navigation during delayed auth restoration finishes boot on the current company", async ({
  page,
}) => {
  await page.goto("/");
  await loginClient(page);
  const companyA = "e230a446-129b-570f-b450-3cd8f7ddc8e5";
  await page
    .getByLabel("Ваша компания", { exact: true })
    .selectOption(companyA);
  await expect(
    page.getByRole("heading", { name: "ООО «Сильный бизнес»" }),
  ).toBeVisible();
  await page
    .getByLabel("Ваша компания", { exact: true })
    .selectOption({ label: "ООО «Неактивный бизнес» · 9900000049" });
  await expect(
    page.getByRole("heading", { name: "ООО «Неактивный бизнес»" }),
  ).toBeVisible();
  let release!: () => void;
  let started!: () => void;
  let delivered!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  const pending = new Promise<void>((resolve) => (started = resolve));
  const completed = new Promise<void>((resolve) => (delivered = resolve));
  await page.route("**/api/v1/auth/me", async (route) => {
    const response = await route.fetch();
    started();
    await held;
    await route.fulfill({ response });
    delivered();
  });
  await page.reload();
  await pending;
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`company=${companyA}$`));
  release();
  await completed;
  await expect(
    page.getByRole("heading", { name: "ООО «Сильный бизнес»" }),
  ).toBeVisible();
  await expect(page.getByLabel("Ваша компания", { exact: true })).toHaveValue(
    companyA,
  );
});

test("adding a company needs the representative's Госуслуги confirmation in a dialog: person and role shown, Escape cancels, the confirmation belongs to its ИНН", async ({
  page,
}) => {
  await registerClient(page, "gosuslugi");
  const verifications: { id: string; inn: string }[] = [];
  page.on("response", async (response) => {
    if (
      response.url().endsWith("/identity/gosuslugi/verify") &&
      response.status() === 201
    ) {
      const body = await response.json();
      verifications.push({ id: body.verification_id, inn: body.inn });
    }
  });
  await page
    .locator(".sidebar")
    .getByRole("button", { name: "Добавить компанию" })
    .click();
  const trigger = page.getByRole("button", {
    name: "Подтвердить через Госуслуги",
  });
  const add = page.getByRole("button", { name: "Добавить и проверить" });
  // Nothing to confirm before an ИНН is chosen.
  await expect(trigger).toBeDisabled();
  await page.getByRole("button").filter({ hasText: "Сильный бизнес" }).click();
  for (const checkbox of await page
    .locator("#onboarding-consents")
    .getByRole("checkbox")
    .all())
    await checkbox.check();
  await expect(add).toBeDisabled();
  await expect(page.locator(".onboarding-remaining")).toContainText(
    "подтвердить полномочия",
  );

  // The dialog shows who Госуслуги returned for this company; Escape closes it without a confirmation.
  await trigger.click();
  const dialog = authorityDialog(page);
  await expect(dialog).toBeVisible();
  for (const text of [
    "Соколов Андрей Викторович",
    "Генеральный директор",
    "ООО «Сильный бизнес»",
    "9900000017",
  ])
    await expect(dialog).toContainText(text);
  await expect(
    dialog.getByRole("button", { name: "Подтвердить" }),
  ).toBeFocused();
  await expect(dialog.locator("img")).toHaveCount(0);
  await dialog.screenshot({ path: `${revision}/task-11-gosuslugi-dialog.png` });
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await expect(page.getByRole("status")).toHaveCount(0);
  await expect(add).toBeDisabled();

  // «Отмена» closes it too; «Подтвердить» confirms, moves focus to the confirmation and enables adding.
  await trigger.click();
  await dialog.getByRole("button", { name: "Отмена" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(add).toBeDisabled();
  await confirmAuthority(page);
  const confirmed = page.getByRole("status");
  await expect(confirmed).toContainText("Соколов Андрей Викторович");
  await expect(confirmed).toContainText("Генеральный директор");
  await expect(confirmed).toBeFocused();
  await expect(add).toBeEnabled();
  await page
    .locator("#gosuslugi-step")
    .screenshot({ path: `${revision}/task-11-gosuslugi-confirmed.png` });

  // Another ИНН needs its own confirmation; coming back to the first one asks again too.
  await page.getByRole("button").filter({ hasText: "Средний риск" }).click();
  await expect(page.getByRole("status")).toHaveCount(0);
  await expect(add).toBeDisabled();
  await page.getByRole("button").filter({ hasText: "Сильный бизнес" }).click();
  await expect(add).toBeDisabled();

  // A mistyped ИНН is caught in the field, before Госуслуги is asked: its check digit does not match.
  const innField = page.getByLabel("ИНН компании или ИП");
  await innField.fill("9912345673");
  await expect(innField).toHaveAttribute("aria-invalid", "true");
  await expect(innField).toHaveAccessibleDescription(
    /Неверная контрольная сумма ИНН/,
  );
  await expect(trigger).toBeDisabled();
  // A well-formed ИНН outside the registry: the dialog explains the refusal and offers no repeat, which could only be
  // refused again; Escape closes it.
  await innField.fill("9912345672");
  await expect(innField).not.toHaveAttribute("aria-invalid");
  await trigger.click();
  await expect(dialog.getByRole("alert")).toContainText("не найден");
  await expect(dialog.getByRole("button", { name: "Повторить" })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "Отмена" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);

  // The company is added with the verification confirmed in the dialog.
  await page.getByRole("button").filter({ hasText: "Сильный бизнес" }).click();
  await confirmAuthority(page);
  await add.click();
  await expect(
    page.getByRole("heading", { name: "Что удалось узнать" }),
  ).toBeVisible();
  const { items } = await (await page.request.get("/api/v1/companies")).json();
  expect(items).toHaveLength(1);
  expect(verifications.length).toBe(4);
  expect(items[0].authority_verification_id).toBe(verifications.at(-1)!.id);
  expect(
    verifications.every((verification) => verification.inn === "9900000017"),
  ).toBe(true);
});

test("a refused add is cleared by choosing another company or a new confirmation; a lost Госуслуги answer is repeated with its key", async ({
  page,
}) => {
  await registerClient(page, "gosuslugi-retry");
  await page
    .locator(".sidebar")
    .getByRole("button", { name: "Добавить компанию" })
    .click();
  // The first check gets no answer (the request is dropped by the route), the second a server failure: each time the
  // dialog says so and offers a retry.
  const keys: string[] = [];
  await page.route("**/identity/gosuslugi/verify", async (route) => {
    keys.push(route.request().headers()["idempotency-key"]);
    if (keys.length === 1) await route.abort();
    else if (keys.length === 2)
      await route.fulfill({
        status: 500,
        json: {
          error: {
            code: "INTERNAL_ERROR",
            message: "Не удалось выполнить запрос. Повторите попытку.",
          },
        },
      });
    else await route.continue();
  });
  await page.getByRole("button").filter({ hasText: "Сильный бизнес" }).click();
  await page
    .getByRole("button", { name: "Подтвердить через Госуслуги" })
    .click();
  const dialog = authorityDialog(page);
  await expect(dialog.getByRole("alert")).toContainText("Нет связи с сервером");
  const retry = dialog.getByRole("button", { name: "Повторить" });
  await expect(retry).toBeFocused();
  await expect(dialog.getByRole("button", { name: "Подтвердить" })).toHaveCount(0);
  await retry.click();
  await expect(dialog.getByRole("alert")).toContainText(
    "Не удалось выполнить запрос",
  );
  await expect(retry).toBeFocused();
  await retry.click();
  await expect(dialog).toContainText("Соколов Андрей Викторович");
  await expect(dialog.getByRole("button", { name: "Подтвердить" })).toBeFocused();
  await expect(dialog.getByRole("alert")).toHaveCount(0);
  // Each repeat is the same check: the same key, so a check the server did record is replayed, not made twice.
  expect(keys).toHaveLength(3);
  expect(new Set(keys).size).toBe(1);
  await dialog.getByRole("button", { name: "Подтвердить" }).click();
  await expect(dialog).toHaveCount(0);
  await page.unroute("**/identity/gosuslugi/verify");
  for (const checkbox of await page
    .locator("#onboarding-consents")
    .getByRole("checkbox")
    .all())
    await checkbox.check();
  await page.getByRole("button", { name: "Добавить и проверить" }).click();
  await expect(
    page.getByRole("heading", { name: "Что удалось узнать" }),
  ).toBeVisible();

  // Adding the same company again is refused; the refusal goes once the client moves on.
  const refusal = page.getByText("Компания уже добавлена. Выберите её в списке.");
  const addAgain = async () => {
    await page.getByRole("button").filter({ hasText: "Сильный бизнес" }).click();
    await confirmAuthority(page);
    for (const checkbox of await page
      .locator("#onboarding-consents")
      .getByRole("checkbox")
      .all())
      await checkbox.check();
    await page.getByRole("button", { name: "Добавить и проверить" }).click();
    await expect(refusal).toBeVisible();
  };
  await page
    .locator(".sidebar")
    .getByRole("button", { name: "Добавить компанию" })
    .click();
  await addAgain();
  await page.getByRole("button").filter({ hasText: "Средний риск" }).click();
  await expect(refusal).toHaveCount(0);
  await addAgain();
  // A new confirmation (for the same company) clears it too.
  await page.getByRole("button", { name: "Подтвердить заново" }).click();
  await authorityDialog(page).getByRole("button", { name: "Подтвердить" }).click();
  await expect(authorityDialog(page)).toHaveCount(0);
  await expect(refusal).toHaveCount(0);
});

test("the ИНН field refuses exactly what the server refuses: a wrong check digit or one repeated digit, for ООО and ИП", async ({
  page,
}) => {
  await registerClient(page, "inn-rule");
  await page
    .locator(".sidebar")
    .getByRole("button", { name: "Добавить компанию" })
    .click();
  const field = page.getByLabel("ИНН компании или ИП");
  const trigger = page.getByRole("button", {
    name: "Подтвердить через Госуслуги",
  });
  const origin = new URL(page.url()).origin;
  // Hand-checked against the standard check digits; none is a listed company, so the server confirms none of them.
  const cases: [string, boolean][] = [
    ["9912345672", true],
    ["9912345673", false], // the tenth digit should be 2
    ["0000000000", false], // the check digit holds, but one digit repeated is no ИНН
    ["991234567818", true],
    ["991234567808", false], // the eleventh digit should be 1
    ["991234567819", false], // the twelfth digit should be 8
    ["000000000000", false],
  ];
  for (const [inn, valid] of cases) {
    await field.fill(inn);
    if (valid) {
      await expect(trigger, inn).toBeEnabled();
      await expect(field, inn).not.toHaveAttribute("aria-invalid");
    } else {
      await expect(trigger, inn).toBeDisabled();
      await expect(field, inn).toHaveAttribute("aria-invalid", "true");
    }
    // The server's own verdict on the same number: a field error, or a number it merely does not know.
    const answer = await page.request.post("/api/v1/identity/gosuslugi/verify", {
      data: { inn },
      headers: { Origin: origin, "Idempotency-Key": crypto.randomUUID() },
    });
    expect([inn, answer.status(), (await answer.json()).error.code]).toEqual([
      inn,
      422,
      valid ? "REGISTRY_NOT_FOUND" : "VALIDATION_ERROR",
    ]);
  }
});

test("a company retry refused for an outdated version is not sent again: the next one starts afresh on the version shown by then", async ({
  page,
}) => {
  await registerClient(page, "retry-refused");
  await onboard(page, "Сильный бизнес");
  const sent: { key: string; version: number; status: number }[] = [];
  page.on("response", (response) => {
    if (
      response.request().method() === "POST" &&
      response.url().endsWith("/precheck/retry")
    )
      sent.push({
        key: response.request().headers()["idempotency-key"],
        version: response.request().postDataJSON().version,
        status: response.status(),
      });
  });
  // Another tab of the same client repeats the check first, so this tab shows an outdated company version.
  const other = await page.context().newPage();
  await other.goto(page.url());
  await other.getByRole("button", { name: "Повторить проверку" }).click();
  await expect(
    other.getByRole("button", { name: "Повторить проверку" }),
  ).toBeEnabled();
  await other.close();
  const retry = page.getByRole("button", { name: "Повторить проверку" });
  await retry.click();
  await expect(page.getByRole("alert")).toContainText("Компания уже обновлена");
  // Coming back to the company loads its current version; the refused attempt stays refused, not resent.
  await page.locator(".sidebar").getByRole("button", { name: "Мои заявки" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Мои заявки" }),
  ).toBeVisible();
  await page
    .locator(".sidebar")
    .getByRole("button", { name: "Мои компании" })
    .click();
  await expect(
    page.getByRole("heading", { name: "ООО «Сильный бизнес»" }),
  ).toBeVisible();
  await retry.click();
  await expect(retry).toBeEnabled();
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(sent.map(({ status }) => status)).toEqual([409, 200]);
  expect(sent[1].key).not.toBe(sent[0].key);
  expect(sent[1].version).toBe(sent[0].version + 1);
});
