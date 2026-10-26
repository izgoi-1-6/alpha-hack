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
 * How far to scroll the page so the highlighted box sits in the free band of the viewport (between `free.top` and
 * `free.bottom`, keeping `margin`): nothing when it is already there and `stay` allows; otherwise the box and `below`
 * (the room the popover needs under it) centred when both fit, the box alone centred when it fits, else its top at
 * the band's top.
 */
export function scrollOffset(
  target: Box,
  free: { top: number; bottom: number },
  below: number,
  margin: number,
  stay: boolean,
): number {
  const top = free.top + margin;
  const room = free.bottom - margin - top;
  if (stay && target.top >= top && target.top + target.height <= top + room)
    return 0;
  const block = target.height + below;
  if (block <= room) return target.top - (top + (room - block) / 2);
  if (target.height <= room)
    return target.top - (top + (room - target.height) / 2);
  return target.top - top;
}
