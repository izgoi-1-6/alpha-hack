import {
  KeyboardEvent,
  RefObject,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  boxAround,
  earlierStep,
  findStep,
  firstControl,
  pageLoading,
  topInset,
} from "./anchors";
import { TourState } from "./persistence";
import { Box, placePopover, popoverScroll, scrollOffset } from "./placement";
import { Side, TOUR_STEPS } from "./steps";
import { TourPopover } from "./TourPopover";
import { TourController } from "./useTour";
import "./tour.css";

/** Below this width the walkthrough is a bottom sheet; the app's phone layout (sticky top bar) starts here too. */
const PHONE = "(max-width: 760px)";
const REDUCED = "(prefers-reduced-motion: reduce)";
/** Spotlight padding around the anchors, popover distance from the spotlight, distance from the viewport edges. */
const PAD = 8;
const GAP = 12;
const MARGIN = 16;
/** The free band above a bottom sheet keeps a smaller margin: phones have little height to spare. */
const SHEET_MARGIN = 8;
/** How long the page must stay still before a popover without room gives way to the sheet. */
const SETTLE_MS = 150;
const SIDES: Side[] = ["bottom", "top", "right", "left"];
const LAST = TOUR_STEPS.length - 1;

/** The box reaches into the viewport. */
const onScreen = (box: Box, width: number, height: number) =>
  box.top < height &&
  box.top + box.height > 0 &&
  box.left < width &&
  box.left + box.width > 0;

/**
 * The mount point: the open walkthrough, mounted afresh for every opening. `onEmptyPage` opens «Мои компании», where
 * the walkthrough begins: used once by an opening from «Как это работает» when the loaded page shows none of its steps.
 */
export function Tour({
  tour,
  route,
  onEmptyPage,
}: {
  tour: TourController;
  route: string;
  onEmptyPage: () => void;
}) {
  if (tour.run === null) return null;
  return (
    <Walkthrough
      key={tour.run.id}
      route={route}
      trigger={tour.trigger}
      onSave={tour.save}
      onClose={tour.close}
      onEmptyPage={tour.run.restart ? onEmptyPage : null}
    />
  );
}

/**
 * The open walkthrough: a spotlight over the current step's anchors and a non-modal popover beside them, or a bottom
 * sheet on phones and wherever no side has room. The page stays usable: the client acts on the highlighted controls,
 * and a new page brings the first remaining step found on it. «Далее» and «Назад» move within a page; a step whose
 * anchors are absent is skipped; while the page shows none of the remaining steps, or a modal dialog or the phone
 * menu is open, nothing is drawn. Reaching the last step completes the walkthrough; leaving its page or pressing
 * «Готово» closes it, «Пропустить» or Escape before it skips it.
 */
function Walkthrough({
  route,
  trigger,
  onSave,
  onClose,
  onEmptyPage,
}: {
  route: string;
  trigger: RefObject<HTMLButtonElement>;
  onSave: (state: TourState) => void;
  onClose: () => void;
  onEmptyPage: (() => void) | null;
}) {
  // The position: forward with «Далее», a new page or a skipped step; back only with «Назад».
  const [index, setIndex] = useState(0);
  // The step on screen and its «Назад» target; `current` is null while the page shows none of the remaining steps.
  const [current, setCurrent] = useState<number | null>(null);
  const [back, setBack] = useState<number | null>(null);
  // A modal dialog of the page (the Госуслуги check, unsaved answers) or the phone menu is open: the walkthrough steps
  // aside.
  const [covered, setCovered] = useState(false);
  const [phone, setPhone] = useState(() => matchMedia(PHONE).matches);
  // No side had room for the popover beside the current step: the sheet takes over until the step changes.
  const [fallback, setFallback] = useState(false);
  const sheet = phone || fallback;
  const popover = useRef<HTMLDivElement>(null);
  const spotlight = useRef<HTMLDivElement>(null);
  const spacer = useRef<HTMLDivElement>(null);
  const primary = useRef<HTMLButtonElement>(null);
  const anchors = useRef<HTMLElement[]>([]);
  const completed = useRef(false);
  const frame = useRef(0);
  const settling = useRef(0);
  // Until the first step is found: a restart on a page without steps opens «Мои компании» (once it has loaded).
  const empty = useRef(onEmptyPage);
  // Scrolling to the step and moving focus into it answer a request — the opening, «Далее»/«Назад», a new page —
  // never a late re-render of the page; a request lapses once the client works elsewhere on the page. A switch to
  // the sheet after the client's own scrolling only brings the step back into view (`reflow`), without focus.
  const pending = useRef(true);
  const reflow = useRef(false);
  const [request, setRequest] = useState(0);
  const ask = () => {
    pending.current = true;
    setRequest((n) => n + 1);
  };
  // Set while the walkthrough moves focus itself, which is not the client working elsewhere.
  const ownFocus = useRef(false);
  const focusTrigger = () => {
    ownFocus.current = true;
    trigger.current?.focus();
    ownFocus.current = false;
  };

  /** The popover's sides and size beside the anchors, within the workspace column it is mounted in. */
  function layout(step: number, box: HTMLDivElement) {
    const view = document.documentElement;
    const column = box.parentElement?.getBoundingClientRect().left ?? 0;
    return {
      target: boxAround(anchors.current, PAD),
      size: { width: box.offsetWidth, height: box.offsetHeight },
      area: {
        top: 0,
        left: column,
        width: view.clientWidth - column,
        height: view.clientHeight,
      },
      sides: TOUR_STEPS[step].sides ?? SIDES,
      column,
    };
  }

  /**
   * Spotlight around the anchors; the popover on a free side beside them (clear of the sidebar), or the sheet along
   * the bottom of the workspace column with room below the page. The spotlight stays out of the sheet and the sticky
   * top bar: a step taller than the band between them is marked down to the sheet. False when no side had room.
   */
  function position(step: number) {
    const light = spotlight.current;
    const box = popover.current;
    if (!light || !box || !anchors.current.length) return true;
    const { target, size, area, sides, column } = layout(step, box);
    const width = area.left + area.width;
    // The hole stays within the band the step may use, so the shadow around it dims all of the viewport even while
    // the anchors are scrolled far away; the ring shows only around a visible hole.
    const minY = sheet ? topInset() : -1;
    const maxY = sheet ? area.height - size.height : area.height + 1;
    const clampX = (x: number) => Math.min(Math.max(x, -1), width + 1);
    const clampY = (y: number) => Math.min(Math.max(y, minY), maxY);
    const top = clampY(target.top);
    const left = clampX(target.left);
    const height = Math.max(0, clampY(target.top + target.height) - top);
    const holeWidth = Math.max(0, clampX(target.left + target.width) - left);
    light.style.top = `${top}px`;
    light.style.left = `${left}px`;
    light.style.width = `${holeWidth}px`;
    light.style.height = `${height}px`;
    light.style.setProperty(
      "--ring",
      height > 2 && holeWidth > 2 ? "2px" : "0px",
    );
    if (sheet) {
      box.style.top = "";
      box.style.left = `${column}px`;
      // The page can scroll its end out from under the sheet.
      if (spacer.current) spacer.current.style.height = `${size.height}px`;
      return true;
    }
    const spot = placePopover(target, size, area, sides, GAP, MARGIN);
    box.style.top = `${spot.top}px`;
    box.style.left = `${spot.left}px`;
    return spot.fits;
  }

  /**
   * Finds the step to show on the page as it is now and lays it out. `settled`: the page has been still for a while,
   * so a popover still without room beside visible anchors gives way to the sheet.
   */
  const update = useRef((settled?: boolean) => {});
  update.current = (settled = false) => {
    const modal =
      document.querySelector("dialog[open]") !== null ||
      (phone && document.querySelector(".sidebar.open") !== null);
    if (modal !== covered) {
      setCovered(modal);
      // Back from a dialog or the menu, which may have moved the page (focus returned into it): the step comes back
      // into view, without taking focus.
      if (!modal) reflow.current = true;
    }
    if (modal) return;
    const found = findStep(index);
    if (!found) {
      anchors.current = [];
      // The questionnaire was left after the last step: the walkthrough is over.
      if (current === LAST) return onClose();
      const openStart = empty.current;
      if (openStart && !pageLoading()) {
        empty.current = null;
        return openStart();
      }
      if (current !== null) {
        // Focus inside the popover that goes away waits on «Как это работает» (until a pending step appears).
        if (popover.current?.contains(document.activeElement)) focusTrigger();
        setCurrent(null);
      }
      return;
    }
    anchors.current = found.elements;
    empty.current = null;
    if (found.index !== index) setIndex(found.index);
    if (found.index !== current) {
      setCurrent(found.index);
      setFallback(false);
    }
    const earlier = earlierStep(found.index);
    if (earlier !== back) setBack(earlier);
    if (found.index === LAST && !completed.current) {
      completed.current = true;
      onSave("done");
    }
    const fits = position(found.index);
    window.clearTimeout(settling.current);
    if (sheet || fits || found.index !== current) return;
    const view = document.documentElement;
    if (
      !onScreen(
        boxAround(found.elements, PAD),
        view.clientWidth,
        view.clientHeight,
      )
    )
      return;
    if (!settled) {
      settling.current = window.setTimeout(
        () => update.current(true),
        SETTLE_MS,
      );
      return;
    }
    reflow.current = true;
    setFallback(true);
  };
  const schedule = () => {
    if (!frame.current)
      frame.current = requestAnimationFrame(() => {
        frame.current = 0;
        update.current();
      });
  };

  const seenRoute = useRef(route);
  useLayoutEffect(() => {
    if (route === seenRoute.current) return;
    seenRoute.current = route;
    ask();
  }, [route]);

  useLayoutEffect(() => {
    update.current();
  }, [index, current, covered, sheet, route]);

  // Answer a pending request once the popover on screen is the found step's: bring the step into the free part of
  // the viewport and move focus into the popover. The popover is kept only where a reachable scroll leaves it a side
  // with room; otherwise the sheet takes over and the request is answered by it.
  useLayoutEffect(() => {
    const box = popover.current;
    if (current === null || current !== index || !box) return;
    if (!pending.current && !reflow.current) return;
    const view = document.documentElement;
    let offset: number;
    if (sheet) {
      offset = scrollOffset(
        boxAround(anchors.current, PAD),
        { top: topInset(), bottom: view.clientHeight - box.offsetHeight },
        0,
        SHEET_MARGIN,
        PAD,
        true,
      );
    } else {
      const { target, size, area, sides } = layout(current, box);
      const planned = popoverScroll(
        target,
        size,
        area,
        sides,
        GAP,
        MARGIN,
        PAD,
        {
          up: window.scrollY,
          down: view.scrollHeight - view.clientHeight - window.scrollY,
        },
      );
      if (planned === null) {
        setFallback(true);
        return;
      }
      offset = planned;
    }
    const focus = pending.current;
    pending.current = reflow.current = false;
    if (Math.abs(offset) >= 1) {
      const instant = matchMedia(REDUCED).matches;
      window.scrollBy({ top: offset, behavior: instant ? "auto" : "smooth" });
      // An instant scroll has already moved the anchors: follow them before the next paint.
      if (instant) position(current);
    }
    if (focus) (primary.current ?? box).focus({ preventScroll: true });
  }, [current, index, request, sheet, covered]);

  // Follow the page: content, size and scroll changes re-lay the step out; working elsewhere lapses a request.
  useEffect(() => {
    const changes = new MutationObserver(schedule);
    changes.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["class", "open", "hidden"],
    });
    const media = matchMedia(PHONE);
    const resize = () => setPhone(media.matches);
    const lapse = (event: Event) => {
      if (!ownFocus.current && !popover.current?.contains(event.target as Node))
        pending.current = false;
    };
    media.addEventListener("change", resize);
    window.addEventListener("scroll", schedule, {
      capture: true,
      passive: true,
    });
    window.addEventListener("resize", schedule);
    document.addEventListener("pointerdown", lapse, true);
    document.addEventListener("focusin", lapse, true);
    return () => {
      cancelAnimationFrame(frame.current);
      window.clearTimeout(settling.current);
      changes.disconnect();
      media.removeEventListener("change", resize);
      window.removeEventListener("scroll", schedule, { capture: true });
      window.removeEventListener("resize", schedule);
      document.removeEventListener("pointerdown", lapse, true);
      document.removeEventListener("focusin", lapse, true);
    };
  }, []);

  // While a step is shown: the highlighted elements and the popover change size without a DOM change too (wrapping,
  // fonts); Shift+Tab from the first highlighted control returns to the popover; Escape skips, wherever focus is.
  useEffect(() => {
    if (current === null || covered) return;
    const sizes = new ResizeObserver(schedule);
    for (const element of anchors.current) sizes.observe(element);
    if (popover.current) sizes.observe(popover.current);
    const keys = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) {
        event.preventDefault();
        stop();
        return;
      }
      if (event.key !== "Tab" || !event.shiftKey) return;
      if (document.activeElement !== firstControl(anchors.current)) return;
      const buttons = popover.current?.querySelectorAll("button");
      if (!buttons?.length) return;
      event.preventDefault();
      buttons[buttons.length - 1].focus();
    };
    document.addEventListener("keydown", keys, true);
    return () => {
      sizes.disconnect();
      document.removeEventListener("keydown", keys, true);
    };
  }, [current, covered]);

  function go(step: number) {
    setIndex(step);
    ask();
  }
  /**
   * «Пропустить», «Готово» and Escape: skipped unless the last step was reached. Focus that was in the walkthrough
   * (or nowhere) returns to the trigger; focus on the page stays where the client was working.
   */
  function stop() {
    if (current !== LAST) onSave("skipped");
    const active = document.activeElement;
    if (
      !active ||
      active === document.body ||
      popover.current?.contains(active)
    )
      focusTrigger();
    onClose();
  }
  /** Tab from the popover's last button goes to the first highlighted control. */
  function tab(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab" || event.shiftKey) return;
    const buttons = popover.current?.querySelectorAll("button");
    if (!buttons?.length) return;
    if (document.activeElement !== buttons[buttons.length - 1]) return;
    const control = firstControl(anchors.current);
    if (!control) return;
    event.preventDefault();
    control.focus();
  }

  if (current === null || covered) return null;
  const step = TOUR_STEPS[current];
  const next =
    current < LAST && TOUR_STEPS[current + 1].page === step.page
      ? current + 1
      : null;
  return (
    <>
      <div ref={spotlight} className="tour-spotlight" aria-hidden="true" />
      <TourPopover
        key={current}
        step={step}
        number={current + 1}
        total={TOUR_STEPS.length}
        sheet={sheet}
        popoverRef={popover}
        primaryRef={primary}
        onBack={back === null ? null : () => go(back)}
        onNext={next === null ? null : () => go(next)}
        onStop={stop}
        onKeyDown={tab}
      />
      {sheet && <div ref={spacer} className="tour-spacer" aria-hidden="true" />}
    </>
  );
}
