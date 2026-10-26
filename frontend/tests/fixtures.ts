import { test as base } from "@playwright/test";

/**
 * Runs in every page before the app: every account's walkthrough flag (`credit-route.tour.v1.<userId>`) reads as
 * done, so the walkthrough never opens by itself. The other storage keys are untouched.
 */
function walkthroughDone() {
  const read = Storage.prototype.getItem;
  Storage.prototype.getItem = function (this: Storage, key: string) {
    return key.startsWith("credit-route.tour.v1.")
      ? "done"
      : read.call(this, key);
  };
}

/**
 * The browser tests' `test`: the client walkthrough (Task 12) starts automatically for a new client, so every
 * context gets the init script above unless a spec opts in with `test.use({ tour: true })` (tour.spec.ts). The
 * officer's own context (`officerPage`) needs none: officers never see the walkthrough.
 */
export const test = base.extend<{ tour: boolean }>({
  tour: [false, { option: true }],
  context: async ({ context, tour }, use) => {
    if (!tour) await context.addInitScript(walkthroughDone);
    await use(context);
  },
});
