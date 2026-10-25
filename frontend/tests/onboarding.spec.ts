import { test, expect } from "@playwright/test";
import { artifacts, confirmAuthority, settle } from "./helpers";

test("seeded demo login, source details, retry and persistent refresh", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "С возвращением" }),
  ).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: artifacts + "/task-2-login-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Демо-клиент", exact: true }).click();
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
  await page.getByLabel("Ваше имя").fill("Демо Предприниматель");
  await page
    .getByLabel("Электронная почта")
    .fill(`browser-${Date.now()}@example.test`);
  await page.getByLabel("Пароль", { exact: true }).fill("DemoCredit2026!");
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
    await page
      .getByRole("button", { name: "Демо-клиент", exact: true })
      .click();
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
    await page
      .getByRole("button", { name: "Демо-клиент", exact: true })
      .click();
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
  await page.getByRole("button", { name: "Демо-клиент", exact: true }).click();
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
  await page.getByRole("button", { name: "Демо-клиент", exact: true }).click();
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
