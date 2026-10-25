import { AmountSliderConfig } from "../../api";

/*
 * The amount slider's scale, read from the catalog's `amount_slider` policy: track positions follow ln(amount)
 * between the bounds, and every amount the slider produces lies on the policy's grid — a band holds the amounts
 * above the previous band's `up_to_rub` up to its own, in multiples of its `step_rub` (the server's check of the
 * policy uses the same rule, so bounds, default, presets and product minimums land on it exactly).
 */

type Band = AmountSliderConfig["snap"][number];

const bandIndex = (bands: Band[], amount: number) => {
  const index = bands.findIndex((band) => amount <= band.up_to_rub);
  return index === -1 ? bands.length - 1 : index;
};
const lowerEdge = (bands: Band[], index: number) =>
  index === 0 ? -Infinity : bands[index - 1].up_to_rub;

export function onGrid(config: AmountSliderConfig, amount: number) {
  if (amount < config.min_rub || amount > config.max_rub) return false;
  return amount % config.snap[bandIndex(config.snap, amount)].step_rub === 0;
}

/** The smallest grid amount above `amount` (the maximum itself at the top). */
export function nextAmount(config: AmountSliderConfig, amount: number) {
  const bands = config.snap;
  for (let i = bandIndex(bands, amount); i < bands.length; i += 1) {
    const step = bands[i].step_rub;
    const from = Math.max(
      Math.floor(amount) + 1,
      lowerEdge(bands, i) + 1,
      config.min_rub,
    );
    const candidate = Math.ceil(from / step) * step;
    if (candidate <= Math.min(bands[i].up_to_rub, config.max_rub))
      return candidate;
  }
  return config.max_rub;
}

/** The largest grid amount below `amount` (the minimum itself at the bottom). */
export function previousAmount(config: AmountSliderConfig, amount: number) {
  const bands = config.snap;
  for (let i = bandIndex(bands, amount); i >= 0; i -= 1) {
    const step = bands[i].step_rub;
    const to = Math.min(
      Math.ceil(amount) - 1,
      bands[i].up_to_rub,
      config.max_rub,
    );
    const candidate = Math.floor(to / step) * step;
    if (candidate > lowerEdge(bands, i) && candidate >= config.min_rub)
      return candidate;
  }
  return config.min_rub;
}

/** The grid amount nearest to `amount`, within the bounds. */
export function snapAmount(config: AmountSliderConfig, amount: number) {
  if (amount <= config.min_rub) return config.min_rub;
  if (amount >= config.max_rub) return config.max_rub;
  const whole = Math.round(amount);
  if (onGrid(config, whole)) return whole;
  const below = previousAmount(config, whole);
  const above = nextAmount(config, whole);
  return whole - below < above - whole ? below : above;
}

/**
 * Track resolution: enough positions that a drag can reach every grid amount, even where a band's step is
 * smallest relative to the amount (at the top of each band).
 */
export function trackSteps(config: AmountSliderConfig) {
  const span = Math.log(config.max_rub / config.min_rub);
  const finest = Math.min(
    ...config.snap.map((band) => band.step_rub / band.up_to_rub),
  );
  return Math.min(10000, Math.max(100, Math.ceil(span / finest)));
}

export function positionOf(
  config: AmountSliderConfig,
  steps: number,
  amount: number,
) {
  const clamped = Math.min(config.max_rub, Math.max(config.min_rub, amount));
  return Math.round(
    (steps * Math.log(clamped / config.min_rub)) /
      Math.log(config.max_rub / config.min_rub),
  );
}

export function amountAt(
  config: AmountSliderConfig,
  steps: number,
  position: number,
) {
  const span = Math.log(config.max_rub / config.min_rub);
  return snapAmount(
    config,
    config.min_rub * Math.exp((span * position) / steps),
  );
}

/** `count` grid steps up (positive) or down (negative) from `amount`. */
export function stepAmount(
  config: AmountSliderConfig,
  amount: number,
  count: number,
) {
  let next = amount;
  for (let i = 0; i < Math.abs(count); i += 1)
    next = count > 0 ? nextAmount(config, next) : previousAmount(config, next);
  return next;
}

/** Track ticks: the bounds and each power of ten between them, with the share of the track where they sit. */
export function ticks(config: AmountSliderConfig) {
  const span = Math.log(config.max_rub / config.min_rub);
  const marks = [config.min_rub];
  for (
    let power = 10 ** Math.ceil(Math.log10(config.min_rub));
    power < config.max_rub;
    power *= 10
  )
    if (power > config.min_rub) marks.push(power);
  marks.push(config.max_rub);
  return marks.map((amount) => ({
    amount,
    share: Math.log(amount / config.min_rub) / span,
  }));
}
