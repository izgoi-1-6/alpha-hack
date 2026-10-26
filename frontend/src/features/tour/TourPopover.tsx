import { KeyboardEvent, RefObject, useId, useState } from "react";
import { Icon } from "../../components";
import { TourStep } from "./steps";

/**
 * The walkthrough's non-modal dialog: «Шаг N из M» with a slim progress bar, the step's title and text, what the
 * client does to go on when the next step is on another page, and the buttons — «Пропустить», «Назад» and «Далее»
 * where they apply, «Готово» on the last step. Its position is set by the walkthrough; `sheet` docks it to the
 * bottom edge. The head and the buttons always stay in view: when the dialog is capped by the screen's height only
 * the text scrolls, and a sheet on a short screen keeps the text behind «Подробнее».
 */
export function TourPopover({
  step,
  number,
  total,
  sheet,
  popoverRef,
  primaryRef,
  onBack,
  onNext,
  onStop,
  onKeyDown,
}: {
  step: TourStep;
  /** The step's position, from 1. */
  number: number;
  total: number;
  sheet: boolean;
  popoverRef: RefObject<HTMLDivElement>;
  /** «Далее» or «Готово», where focus goes on each step. */
  primaryRef: RefObject<HTMLButtonElement>;
  onBack: (() => void) | null;
  onNext: (() => void) | null;
  /** «Пропустить» before the last step, «Готово» on it. */
  onStop: () => void;
  onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => void;
}) {
  const id = useId();
  const [expanded, setExpanded] = useState(false);
  const last = number === total;
  return (
    <div
      ref={popoverRef}
      className={
        "tour-popover" + (sheet ? " sheet" : "") + (expanded ? " expanded" : "")
      }
      role="dialog"
      aria-modal="false"
      aria-labelledby={`${id}-count ${id}-title`}
      aria-describedby={`${id}-text` + (step.action ? ` ${id}-action` : "")}
      tabIndex={-1}
      onKeyDown={onKeyDown}
    >
      <div className="tour-progress" aria-hidden="true">
        <span style={{ width: `${(number / total) * 100}%` }} />
      </div>
      <p id={`${id}-count`} className="tour-count">
        Шаг {number} из {total}
      </p>
      <div className="tour-heading">
        <h2 id={`${id}-title`}>{step.title}</h2>
        <button
          type="button"
          className="tour-more"
          aria-expanded={expanded}
          aria-controls={`${id}-text`}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Свернуть" : "Подробнее"}
        </button>
      </div>
      <div className="tour-body">
        <p id={`${id}-text`} className="tour-text">
          {step.text}
        </p>
        {step.action && (
          <p id={`${id}-action`} className="tour-action">
            <Icon size={18} />
            <span>{step.action}</span>
          </p>
        )}
      </div>
      <div className="tour-actions">
        {!last && (
          <button type="button" className="tour-skip" onClick={onStop}>
            Пропустить
          </button>
        )}
        {onBack && (
          <button type="button" className="button secondary" onClick={onBack}>
            Назад
          </button>
        )}
        {onNext && (
          <button
            ref={primaryRef}
            type="button"
            className="button primary"
            onClick={onNext}
          >
            Далее
          </button>
        )}
        {last && (
          <button
            ref={primaryRef}
            type="button"
            className="button primary"
            onClick={onStop}
          >
            Готово
          </button>
        )}
      </div>
    </div>
  );
}
