/** What the walkthrough remembers per client. Nothing else goes to the browser storage. */
export type TourState = "done" | "skipped";

const key = (userId: string) => `credit-route.tour.v1.${userId}`;
/** The fallback while the browser storage is unavailable: the walkthrough then opens once per page session. */
const memory = new Map<string, TourState>();

export function readTourState(userId: string): TourState | null {
  try {
    const stored = window.localStorage.getItem(key(userId));
    if (stored === "done" || stored === "skipped") return stored;
  } catch {
    // Storage blocked or unavailable: this page session's memory decides.
  }
  return memory.get(userId) ?? null;
}

export function writeTourState(userId: string, state: TourState) {
  memory.set(userId, state);
  try {
    window.localStorage.setItem(key(userId), state);
  } catch {
    // Storage blocked or full: the memory keeps the walkthrough closed until the page is reloaded.
  }
}
