import {
  CSSProperties,
  KeyboardEvent,
  ReactNode,
  Ref,
  useEffect,
  useMemo,
  useState,
} from "react";
import { AmountSliderConfig } from "../../api";
import { parseInteger } from "../applications/fields";
import { rub } from "../applications/format";
import {
  amountAt,
  positionOf,
  stepAmount,
  ticks,
  trackSteps,
} from "./amountScale";

const NBSP = " ";
/** «2 000 000»: an amount as the field shows it, digit groups kept together. */
const grouped = (amount: number) =>
  new Intl.NumberFormat("ru-RU").format(amount).replace(/\s/g, NBSP);
/** «500 тыс. ₽», «1,5 млн ₽»: the short labels of presets and ticks. */
export const compactRub = (amount: number) =>
  new Intl.NumberFormat("ru-RU", {
    notation: "compact",
    maximumFractionDigits: 1,
  })
    .format(amount)
    .replace(/\s/g, NBSP) +
  NBSP +
  "₽";

/** A typed amount: a whole number of rubles within the slider's bounds, or why it cannot be used. */
function readTyped(config: AmountSliderConfig, text: string) {
  const parsed = parseInteger(text);
  const maximum = `Максимальная сумма — ${rub(config.max_rub)}.`;
  if (parsed.error)
    return {
      amount: null,
      // Digits too many for a safe number are still an amount, above the maximum: not a typing mistake.
      error: /^\d+$/.test(text.replace(/[\s\u00a0]/g, ""))
        ? maximum
        : "Введите сумму цифрами, например 2 500 000.",
    };
  if (parsed.value === null) return { amount: null, error: "Укажите сумму." };
  if (parsed.value < config.min_rub)
    return {
      amount: null,
      error: `Минимальная сумма — ${rub(config.min_rub)}.`,
    };
  if (parsed.value > config.max_rub) return { amount: null, error: maximum };
  return { amount: parsed.value, error: null };
}

/** Keys of the track: one grid step for the arrows, ten for PageUp/PageDown, the bounds for Home/End. */
const KEY_STEPS: Record<string, number> = {
  ArrowRight: 1,
  ArrowUp: 1,
  ArrowLeft: -1,
  ArrowDown: -1,
  PageUp: 10,
  PageDown: -10,
};

/**
 * The product screen's only input: the amount as a large typed value and a log-scale slider with presets, all
 * from the catalog's `amount_slider` policy. The slider and the keys move along the policy's grid; a typed amount
 * is kept exactly as typed. A typed text that cannot be used is reported here and passed up as null.
 */
export function AmountSlider({
  config,
  amount,
  onChange,
  sliderRef,
  children,
}: {
  config: AmountSliderConfig;
  /** The amount the cards are for: the last usable one while the typed text is not. */
  amount: number;
  onChange: (amount: number | null) => void;
  /** The slider, for the page to move focus to after changing the amount itself (the text field would open a
   * phone's keyboard). */
  sliderRef?: Ref<HTMLInputElement>;
  /** Context shown beside the amount (the company's turnover). */
  children?: ReactNode;
}) {
  const steps = useMemo(() => trackSteps(config), [config]);
  // Inner ticks too close to a bound would collide with its label.
  const marks = useMemo(
    () =>
      ticks(config).filter(
        (mark, index, all) =>
          index === 0 ||
          index === all.length - 1 ||
          (mark.share > 0.1 && mark.share < 0.88),
      ),
    [config],
  );
  const [text, setText] = useState(() => grouped(amount));
  const [error, setError] = useState<string | null>(null);
  // An amount set elsewhere (a card's «Рассчитать на …») replaces the text, unless the text already says it.
  useEffect(() => {
    if (parseInteger(text).value !== amount) {
      setText(grouped(amount));
      setError(null);
    }
  }, [amount]);

  function choose(next: number) {
    setText(grouped(next));
    setError(null);
    onChange(next);
  }
  function type(value: string) {
    const typed = readTyped(config, value);
    setText(value);
    setError(typed.error);
    onChange(typed.amount);
  }
  function key(event: KeyboardEvent<HTMLInputElement>) {
    // With Alt, Ctrl or Cmd held the keys are the browser's (Back/Forward, word and line jumps).
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const next =
      event.key === "Home"
        ? config.min_rub
        : event.key === "End"
          ? config.max_rub
          : event.key in KEY_STEPS
            ? stepAmount(config, amount, KEY_STEPS[event.key])
            : null;
    if (next === null) return;
    event.preventDefault();
    choose(next);
  }
  const position = positionOf(config, steps, amount);

  return (
    <section
      id="amount-picker"
      className="card amount-picker"
      aria-labelledby="amount-heading"
    >
      <div className="amount-main" data-tour="amount-field">
        <div className="eyebrow">Ваша задача</div>
        <h2 id="amount-heading">Какая сумма нужна бизнесу?</h2>
        <label className="amount-label" htmlFor="amount-input">
          Сумма, ₽
        </label>
        <div className={"amount-value" + (error ? " invalid" : "")}>
          <input
            id="amount-input"
            inputMode="numeric"
            autoComplete="off"
            value={text}
            onChange={(event) => type(event.target.value)}
            onBlur={() => {
              const typed = readTyped(config, text);
              if (typed.amount !== null) setText(grouped(typed.amount));
            }}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "amount-error" : "amount-hint"}
          />
          <span aria-hidden="true">₽</span>
        </div>
        {error && (
          <p id="amount-error" className="amount-error" role="alert">
            {error}
          </p>
        )}
      </div>
      {children && <div className="amount-aside">{children}</div>}
      <div className="amount-track" data-tour="amount-slider">
        <input
          ref={sliderRef}
          id="amount-slider"
          className="amount-range"
          type="range"
          min={0}
          max={steps}
          step={1}
          value={position}
          style={{ "--fill": `${(position / steps) * 100}%` } as CSSProperties}
          onChange={(event) =>
            choose(amountAt(config, steps, event.target.valueAsNumber))
          }
          onKeyDown={key}
          aria-label="Сумма финансирования"
          aria-valuetext={rub(amount)}
          aria-describedby="amount-hint"
        />
        <div className="amount-ticks" aria-hidden="true">
          {marks.map((mark, index) => (
            <span
              key={mark.amount}
              className={
                index === 0 || index === marks.length - 1 ? "edge" : undefined
              }
              style={{ "--at": mark.share } as CSSProperties}
            >
              {compactRub(mark.amount)}
            </span>
          ))}
        </div>
      </div>
      <div
        className="amount-presets"
        role="group"
        aria-label="Быстрый выбор суммы"
      >
        {config.presets_rub.map((preset) => (
          <button
            key={preset}
            type="button"
            aria-pressed={!error && amount === preset}
            onClick={() => choose(preset)}
          >
            {compactRub(preset)}
          </button>
        ))}
      </div>
      <p id="amount-hint" className="amount-hint">
        Шкала от {rub(config.min_rub)} до {rub(config.max_rub)}; точную сумму
        можно ввести цифрами. Цель, срок и залог выберете в анкете продукта.
      </p>
    </section>
  );
}
