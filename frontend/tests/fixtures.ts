import { test as base } from "@playwright/test";

/**
 * Runs in every page before the app: every account's walkthrough flag (`credit-route.tour.v1.<userId>`) reads as
 * done, so the walkthrough never opens by itself. The other storage keys are untouched (a key is coerced to a string,
 * as `getItem` itself does). Exported for contexts made with `browser.newContext()`, which do not get it:
 * `await context.addInitScript(walkthroughDone)`.
 */
export function walkthroughDone() {
  const read = Storage.prototype.getItem;
  Storage.prototype.getItem = function (this: Storage, key: string) {
    return String(key).startsWith("credit-route.tour.v1.")
      ? "done"
      : read.call(this, key);
  };
}

/**
 * The browser tests' `test`: the client walkthrough (Task 12) starts automatically for a new client, so the test's
 * own `context` (and every page in it) gets the init script above unless a spec opts in with
 * `test.use({ tour: true })` (tour.spec.ts).
 *
 * Only that fixture context gets it: a context made with `browser.newContext()` starts without it, so a client there
 * meets the walkthrough. That is right for the officer's context (`officerPage`: officers never see it); a journey that
 * opens a client in a context of its own must add the exported `walkthroughDone` to it, or expect the walkthrough.
 */
export const test = base.extend<{ tour: boolean }>({
  tour: [false, { option: true }],
  context: async ({ context, tour }, use) => {
    if (!tour) await context.addInitScript(walkthroughDone);
    await use(context);
  },
});
