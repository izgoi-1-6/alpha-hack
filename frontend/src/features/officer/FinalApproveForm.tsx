import { FormEvent, useEffect, useRef, useState } from "react";
import { parseInteger } from "../applications/fields";
import { keepAmountsTogether, rub } from "../applications/format";
import {
  describedBy,
  FieldMessages,
  ReasonField,
  useBoundAmount,
} from "./DecisionForms";
import { FinalApproval } from "./officerApi";

/**
 * The final decision on an accepted packet: an integer amount prefilled to the server's upper bound, with the bounds
 * it comes from, a reason, and a confirmation step. The server alone decides whether the amount is within bounds.
 */
export function FinalApproveForm({
  finalApproval,
  preapprovedAmount,
  busy,
  fields,
  onSubmit,
}: {
  finalApproval: FinalApproval;
  preapprovedAmount: number | null;
  busy: boolean;
  fields: FieldMessages;
  onSubmit: (amount: number, reason: string) => void;
}) {
  const [amount, setAmount] = useBoundAmount(finalApproval.amount_max_rub);
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  // Focus follows the confirmation, as in CancelAction: into it on opening, back to the action on «Вернуться».
  const back = useRef<HTMLButtonElement>(null);
  const action = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  useEffect(() => {
    if (confirming) back.current?.focus();
    else if (restoreFocus.current) {
      restoreFocus.current = false;
      action.current?.focus();
    }
  }, [confirming]);
  const parsed = parseInteger(amount);
  const amountError = parsed.error ?? fields.amount_rub;
  const ready = parsed.value !== null && !parsed.error && !!reason.trim();
  const { amount_min_rub: low, amount_max_rub: high, verified_limit_rub: limit } = finalApproval;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (ready) setConfirming(true);
  }
  return (
    <form className="decision-form" onSubmit={submit} noValidate>
      <h3>Окончательное одобрение</h3>
      {low !== null && high !== null && (
        <p className="field-note" id="approve-bounds">
          Допустимо от {rub(low)} до {rub(high)} включительно: не меньше
          минимума продукта, не больше предварительно одобренной суммы
          {preapprovedAmount !== null ? ` (${rub(preapprovedAmount)})` : ""} и
          лимита по проверенным документам
          {limit !== null ? ` (${rub(limit)})` : ""}.
        </p>
      )}
      <div className="field">
        <label htmlFor="approve-amount">Итоговая сумма, ₽</label>
        <input
          id="approve-amount"
          inputMode="numeric"
          autoComplete="off"
          value={amount}
          disabled={busy}
          aria-invalid={amountError ? true : undefined}
          aria-describedby={describedBy(
            "approve-bounds",
            "approve-amount-hint",
            amountError && "approve-amount-error",
          )}
          onChange={(event) => {
            setConfirming(false);
            setAmount(event.target.value);
          }}
        />
        <p className="field-note" id="approve-amount-hint">
          {parsed.value !== null && !parsed.error
            ? `Указано: ${rub(parsed.value)}.`
            : "Целое число рублей."}
        </p>
        {amountError && (
          <p className="field-error" id="approve-amount-error">
            {keepAmountsTogether(amountError)}
          </p>
        )}
      </div>
      <ReasonField
        id="approve-reason"
        label="Основание решения"
        hint="Сохранится в истории заявки; клиент увидит его вместе с решением."
        value={reason}
        error={fields.reason}
        disabled={busy}
        onChange={(value) => {
          setConfirming(false);
          setReason(value);
        }}
      />
      <p className="decision-caveat">
        Окончательное решение: клиент перейдёт в Альфа-Бизнес, в «Кредитном
        маршруте» договор не подписывается и деньги не перечисляются.
      </p>
      {!confirming ? (
        <button
          ref={action}
          type="submit"
          className="button primary"
          disabled={busy || !ready}
        >
          Одобрить окончательно
        </button>
      ) : (
        <div className="cancel-confirm" role="group" aria-labelledby="approve-confirm-title">
          <h4 id="approve-confirm-title">Одобрить заявку окончательно?</h4>
          <p>
            Итоговая сумма — {parsed.value !== null ? rub(parsed.value) : "—"}.
            Решение нельзя отменить: заявка закроется одобрением.
          </p>
          <div className="form-actions">
            <button
              ref={back}
              type="button"
              className="button secondary"
              disabled={busy}
              onClick={() => {
                restoreFocus.current = true;
                setConfirming(false);
              }}
            >
              Вернуться
            </button>
            <button
              type="button"
              className="button primary"
              disabled={busy || !ready || parsed.value === null}
              onClick={() => {
                if (parsed.value !== null) onSubmit(parsed.value, reason.trim());
              }}
            >
              {busy ? "Отправляем…" : "Да, одобрить"}
            </button>
          </div>
        </div>
      )}
    </form>
  );
}
