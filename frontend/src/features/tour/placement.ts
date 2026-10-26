import { Side } from "./steps";

/** A rectangle in viewport coordinates. */
export type Box = { top: number; left: number; width: number; height: number };
export type Size = { width: number; height: number };

const clamp = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), Math.max(min, max));

/**
 * Where the popover goes beside the highlighted box, inside `area` (keeping `margin` from its edges): the first side
 * in `sides` where it fits without touching the box (`fits`); when none fits, the side that needs the least
 * correction, moved inside the area.
 */
export function placePopover(
  target: Box,
  popover: Size,
  area: Box,
  sides: Side[],
  gap: number,
  margin: number,
): { top: number; left: number; fits: boolean } {
  const minTop = area.top + margin;
  const maxTop = area.top + area.height - margin - popover.height;
  const minLeft = area.left + margin;
  const maxLeft = area.left + area.width - margin - popover.width;
  const across = clamp(
    target.left + target.width / 2 - popover.width / 2,
    minLeft,
    maxLeft,
  );
  const along = clamp(
    target.top + target.height / 2 - popover.height / 2,
    minTop,
    maxTop,
  );
  const at: Record<Side, { top: number; left: number }> = {
    bottom: { top: target.top + target.height + gap, left: across },
    top: { top: target.top - gap - popover.height, left: across },
    right: { top: along, left: target.left + target.width + gap },
    left: { top: along, left: target.left - gap - popover.width },
  };
  const outside = ({ top, left }: { top: number; left: number }) =>
    Math.max(0, minTop - top) +
    Math.max(0, top - maxTop) +
    Math.max(0, minLeft - left) +
    Math.max(0, left - maxLeft);
  const fitting = sides.find((side) => outside(at[side]) === 0);
  const side =
    fitting ??
    sides.reduce((best, candidate) =>
      outside(at[candidate]) < outside(at[best]) ? candidate : best,
    );
  return {
    top: clamp(at[side].top, minTop, maxTop),
    left: clamp(at[side].left, minLeft, maxLeft),
    fits: fitting !== undefined,
  };
}

/**
 * How far to scroll the page so the highlighted box (`target`, which includes `pad` on every side) sits in the free
 * band of the viewport, keeping `margin` from its edges: nothing when it is already there and `stay` allows;
 * otherwise the box and `below` (the room a popover needs under it) centred when both fit, the box alone centred when
 * it fits, the box without its padding centred in the band without margins when that fits, else the box's top at the
 * band's top — only its top part can be shown.
 */
export function scrollOffset(
  target: Box,
  free: { top: number; bottom: number },
  below: number,
  margin: number,
  pad: number,
  stay: boolean,
): number {
  const top = free.top + margin;
  const room = free.bottom - margin - top;
  if (stay && target.top >= top && target.top + target.height <= top + room)
    return 0;
  if (target.height + below <= room)
    return target.top - (top + (room - target.height - below) / 2);
  if (target.height <= room)
    return target.top - (top + (room - target.height) / 2);
  const band = free.bottom - free.top;
  const bare = target.height - 2 * pad;
  if (bare <= band) return target.top + pad - (free.top + (band - bare) / 2);
  return target.top - free.top;
}

/**
 * The scroll after which the popover has a side with room beside the highlighted box, within the page's scroll range
 * (`up` and `down` from where it is): none when the box is in view with such a side already, else the box and the
 * popover under it centred, else the box alone. Null when no reachable position leaves room: the sheet takes over.
 */
export function popoverScroll(
  target: Box,
  popover: Size,
  area: Box,
  sides: Side[],
  gap: number,
  margin: number,
  pad: number,
  range: { up: number; down: number },
): number | null {
  const free = { top: area.top, bottom: area.top + area.height };
  const below = gap + popover.height;
  for (const wanted of [
    scrollOffset(target, free, below, margin, pad, true),
    scrollOffset(target, free, below, margin, pad, false),
    scrollOffset(target, free, 0, margin, pad, false),
  ]) {
    const offset = clamp(wanted, -range.up, range.down);
    const moved = { ...target, top: target.top - offset };
    // In view after the scroll: all of the box, or the top of a box taller than the viewport.
    const shown =
      moved.top >= free.top - 1 &&
      (moved.top + moved.height <= free.bottom + 1 ||
        (moved.height > free.bottom - free.top &&
          moved.top <= free.top + margin + 1));
    if (shown && placePopover(moved, popover, area, sides, gap, margin).fits)
      return offset;
  }
  return null;
}
