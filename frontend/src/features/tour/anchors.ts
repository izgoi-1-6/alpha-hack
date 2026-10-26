import { Box } from "./placement";
import { TOUR_STEPS, TourStep } from "./steps";

/** Laid out and not hidden. */
function shown(element: Element) {
  if (!element.getClientRects().length) return false;
  const box = element.getBoundingClientRect();
  return (
    box.width > 0 &&
    box.height > 0 &&
    getComputedStyle(element).visibility !== "hidden"
  );
}

/** The step's highlighted elements on the current page (the first shown match of each anchor), or null. */
export function anchorsOf(step: TourStep): HTMLElement[] | null {
  const found: HTMLElement[] = [];
  for (const name of step.anchors) {
    const element = [
      ...document.querySelectorAll<HTMLElement>(`[data-tour="${name}"]`),
    ].find(shown);
    if (!element) return null;
    found.push(element);
  }
  return found;
}

/** The first step at or after `from` whose anchors are on the page. */
export function findStep(from: number) {
  for (let index = from; index < TOUR_STEPS.length; index += 1) {
    const elements = anchorsOf(TOUR_STEPS[index]);
    if (elements) return { index, elements };
  }
  return null;
}

/** The nearest earlier step of the same page whose anchors are on the page, for «Назад». */
export function earlierStep(index: number) {
  const page = TOUR_STEPS[index].page;
  for (let i = index - 1; i >= 0 && TOUR_STEPS[i].page === page; i -= 1)
    if (anchorsOf(TOUR_STEPS[i])) return i;
  return null;
}

/** The box around all the elements, grown by `pad` on every side. */
export function boxAround(elements: Element[], pad: number): Box {
  const rects = elements.map((element) => element.getBoundingClientRect());
  const top = Math.min(...rects.map((rect) => rect.top)) - pad;
  const left = Math.min(...rects.map((rect) => rect.left)) - pad;
  const bottom = Math.max(...rects.map((rect) => rect.bottom)) + pad;
  const right = Math.max(...rects.map((rect) => rect.right)) + pad;
  return { top, left, width: right - left, height: bottom - top };
}

/** The app's loading indicator (`Loading`) is on the page: the page's anchors may still come. */
export function pageLoading() {
  return document.querySelector(".loading") !== null;
}

/** The bottom edge of the top bar while it is sticky (phones), else 0: the band above it is not free. */
export function topInset() {
  const bar = document.querySelector(".topbar");
  return bar && getComputedStyle(bar).position === "sticky"
    ? Math.max(0, bar.getBoundingClientRect().bottom)
    : 0;
}

const FOCUSABLE =
  "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex='-1'])";

/** The first keyboard control of the highlighted elements, the elements themselves included. */
export function firstControl(elements: Element[]): HTMLElement | null {
  for (const element of elements)
    for (const candidate of [element, ...element.querySelectorAll(FOCUSABLE)])
      if (
        candidate instanceof HTMLElement &&
        candidate.matches(FOCUSABLE) &&
        shown(candidate)
      )
        return candidate;
  return null;
}
