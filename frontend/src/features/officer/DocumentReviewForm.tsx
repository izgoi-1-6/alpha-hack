import { FormEvent, useState } from "react";
import { ApplicationDocument } from "../../api";
import { parseInteger } from "../applications/fields";
import { keepAmountsTogether } from "../applications/format";
import { documentTitle } from "../documents/documentFormat";
import { describedBy, FieldMessages, ReasonField } from "./DecisionForms";

export type ReviewBody = {
  decision: "accept" | "reject";
  reason: string;
  verified_value_rub?: number;
};

/**
 * Accept or reject one current, unreviewed file with a reason the client will read. Accepting the collateral
 * valuation also records the verified value (a positive whole number of rubles), which bounds the final amount.
 */
export function DocumentReviewForm({
  document,
  busy,
  fields,
  onSubmit,
}: {
  document: ApplicationDocument;
  busy: boolean;
  fields: FieldMessages;
  onSubmit: (body: ReviewBody) => void;
}) {
  const [decision, setDecision] = useState<ReviewBody["decision"] | null>(null);
  const [reason, setReason] = useState("");
  const [value, setValue] = useState("");
  const id = `review-${document.id}`;
  const needsValue = document.document_type === "COLLATERAL_VALUATION" && decision === "accept";
  const parsed = parseInteger(value);
  const valueError = needsValue
    ? (parsed.error ??
      (parsed.value === 0 ? "Укажите стоимость больше нуля" : undefined) ??
      fields.verified_value_rub)
    : undefined;
  const valueReady = !needsValue || (parsed.value !== null && parsed.value > 0 && !parsed.error);
  const ready = !!decision && !!reason.trim() && valueReady;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready || !decision) return;
    onSubmit({
      decision,
      reason: reason.trim(),
      ...(needsValue && parsed.value !== null ? { verified_value_rub: parsed.value } : {}),
    });
  }
  return (
    <form
      className="decision-form document-review-form"
      aria-label={`Проверка документа: ${documentTitle(document.document_type)}`}
      onSubmit={submit}
      noValidate
    >
      <fieldset className="choice-field">
        <legend>Решение по документу</legend>
        <div className="choices">
          {(
            [
              ["accept", "Принять"],
              ["reject", "Отклонить"],
            ] as const
          ).map(([option, label]) => (
            <label key={option} className={"choice" + (decision === option ? " chosen" : "")}>
              <input
                type="radio"
                name={id + "-decision"}
                checked={decision === option}
                disabled={busy}
                onChange={() => setDecision(option)}
              />
              <span>{label}</span>
            </label>
          ))}
        </div>
      </fieldset>
      {needsValue && (
        <div className="field">
          <label htmlFor={id + "-value"}>Проверенная стоимость залога, ₽</label>
          <input
            id={id + "-value"}
            inputMode="numeric"
            autoComplete="off"
            value={value}
            disabled={busy}
            aria-invalid={valueError ? true : undefined}
            aria-describedby={describedBy(id + "-value-hint", valueError && id + "-value-error")}
            onChange={(event) => setValue(event.target.value)}
          />
          <p className="field-note" id={id + "-value-hint"}>
            Целое число рублей по отчёту об оценке: от него рассчитается предел
            итоговой суммы по залогу.
          </p>
          {valueError && (
            <p className="field-error" id={id + "-value-error"}>
              {keepAmountsTogether(valueError)}
            </p>
          )}
        </div>
      )}
      {decision && (
        <ReasonField
          id={id + "-reason"}
          label={decision === "accept" ? "Комментарий к проверке" : "Причина отклонения"}
          hint={
            decision === "accept"
              ? "Сохранится в карточке документа; клиент его увидит."
              : "Клиент увидит причину и заменит файл; комплект вернётся к нему на доработку, срок предварительного одобрения не продлевается."
          }
          value={reason}
          error={fields.reason}
          disabled={busy}
          onChange={setReason}
        />
      )}
      {decision && (
        <button
          type="submit"
          className={"button " + (decision === "accept" ? "primary" : "danger")}
          disabled={busy || !ready}
        >
          {busy ? "Сохраняем…" : decision === "accept" ? "Принять документ" : "Отклонить документ"}
        </button>
      )}
    </form>
  );
}
