import { FormEvent, useEffect, useRef, useState } from "react";
import { ApplicationStatus } from "../../api";
import { parseInteger } from "../applications/fields";
import { keepAmountsTogether, rub } from "../applications/format";
import { Preapproval } from "./officerApi";
import { REQUESTABLE } from "./officerFormat";

/** Field messages of the last refused command of this form (the server's `fields`). */
type FieldMessages = Record<string, string>;

const describedBy = (...ids: (string | false | undefined)[]) =>
  ids.filter(Boolean).join(" ") || undefined;

/** A decision reason or question: 1–2000 characters after trimming, stored in the history the client reads. */
function ReasonField({
  id,
  label,
  hint,
  value,
  error,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  value: string;
  error?: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <textarea
        id={id}
        rows={3}
        maxLength={2000}
        value={value}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id + "-hint", error && id + "-error")}
        onChange={(event) => onChange(event.target.value)}
      />
      <p className="field-note" id={id + "-hint"}>
        {hint} До 2000 символов.
      </p>
      {error && (
        <p className="field-error" id={id + "-error"}>
          {error}
        </p>
      )}
    </div>
  );
}

/** An integer amount prefilled to the upper bound; the server alone decides whether it is within bounds. */
export function PreapproveForm({
  preapproval,
  busy,
  fields,
  onSubmit,
}: {
  preapproval: Preapproval;
  busy: boolean;
  fields: FieldMessages;
  onSubmit: (amount: number, reason: string) => void;
}) {
  const [amount, setAmount] = useState(
    preapproval.amount_max_rub !== null ? String(preapproval.amount_max_rub) : "",
  );
  const [reason, setReason] = useState("");
  const parsed = parseInteger(amount);
  const amountError = parsed.error ?? fields.amount_rub;
  const ready = parsed.value !== null && !parsed.error && !!reason.trim();
  function submit(event: FormEvent) {
    event.preventDefault();
    if (ready && parsed.value !== null) onSubmit(parsed.value, reason.trim());
  }
  return (
    <form className="decision-form" onSubmit={submit} noValidate>
      <h3>Предварительное одобрение</h3>
      {preapproval.amount_min_rub !== null &&
        preapproval.amount_max_rub !== null && (
          <p className="field-note" id="preapprove-bounds">
            Допустимо от {rub(preapproval.amount_min_rub)} до{" "}
            {rub(preapproval.amount_max_rub)} включительно: не меньше минимума
            продукта и не больше запрошенной суммы и расчётного лимита.
          </p>
        )}
      <div className="field">
        <label htmlFor="preapprove-amount">
          Сумма предварительного одобрения, ₽
        </label>
        <input
          id="preapprove-amount"
          inputMode="numeric"
          autoComplete="off"
          value={amount}
          disabled={busy}
          aria-invalid={amountError ? true : undefined}
          aria-describedby={describedBy(
            "preapprove-bounds",
            "preapprove-amount-hint",
            amountError && "preapprove-amount-error",
          )}
          onChange={(event) => setAmount(event.target.value)}
        />
        <p className="field-note" id="preapprove-amount-hint">
          {parsed.value !== null && !parsed.error
            ? `Указано: ${rub(parsed.value)}.`
            : "Целое число рублей."}
        </p>
        {amountError && (
          <p className="field-error" id="preapprove-amount-error">
            {keepAmountsTogether(amountError)}
          </p>
        )}
      </div>
      <ReasonField
        id="preapprove-reason"
        label="Основание решения"
        hint="Сохранится в истории заявки; клиент увидит его вместе с решением."
        value={reason}
        error={fields.reason}
        disabled={busy}
        onChange={setReason}
      />
      <p className="decision-caveat">
        Предварительное одобрение — не окончательное решение: итоговую сумму
        подтвердит проверка документов.
      </p>
      <button type="submit" className="button primary" disabled={busy || !ready}>
        Предварительно одобрить
      </button>
    </form>
  );
}

/** Requestable answers by stage (never the stage-2 need) and the question the client will answer. */
export function RequestInfoForm({
  secured,
  busy,
  fields,
  onSubmit,
}: {
  secured: boolean;
  busy: boolean;
  fields: FieldMessages;
  onSubmit: (paths: string[], question: string) => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const groups = REQUESTABLE.filter((group) => !group.securedOnly || secured);
  const ordered = groups
    .flatMap((group) => group.fields.map((field) => field.path))
    .filter((path) => selected.includes(path));
  const ready = ordered.length > 0 && !!question.trim();
  const toggle = (path: string, on: boolean) =>
    setSelected((current) =>
      on ? [...current, path] : current.filter((entry) => entry !== path),
    );
  function submit(event: FormEvent) {
    event.preventDefault();
    if (ready) onSubmit(ordered, question.trim());
  }
  return (
    <form className="decision-form" onSubmit={submit} noValidate>
      <h3>Запрос сведений у клиента</h3>
      <fieldset
        className="request-fields"
        aria-describedby={describedBy(
          "request-fields-note",
          fields.requested_fields && "request-fields-error",
        )}
      >
        <legend>Какие сведения запросить</legend>
        <p className="field-note" id="request-fields-note">
          Цель, сумма, срок и порядок использования зафиксированы при отправке и
          не запрашиваются. Клиент ответит в форме на странице заявки, и заявка
          вернётся к вам.
        </p>
        {groups.map((group) => (
          <div className="request-group" key={group.title}>
            <span className="request-group-title">{group.title}</span>
            {group.fields.map((field) => (
              <label className="check-row" key={field.path}>
                <input
                  type="checkbox"
                  checked={selected.includes(field.path)}
                  disabled={busy}
                  onChange={(event) => toggle(field.path, event.target.checked)}
                />
                <span>{field.label}</span>
              </label>
            ))}
          </div>
        ))}
        {fields.requested_fields && (
          <p className="field-error" id="request-fields-error">
            {fields.requested_fields}
          </p>
        )}
      </fieldset>
      <ReasonField
        id="request-question"
        label="Вопрос клиенту"
        hint="Клиент увидит вопрос на странице заявки."
        value={question}
        error={fields.reason}
        disabled={busy}
        onChange={setQuestion}
      />
      <button type="submit" className="button primary" disabled={busy || !ready}>
        Отправить запрос
      </button>
      {ordered.length === 0 && (
        <p className="field-note">Отметьте хотя бы одно поле анкеты.</p>
      )}
    </form>
  );
}

/** A rejection is final for the application, so the reason is confirmed in a second step before it is sent. */
export function RejectForm({
  status,
  busy,
  fields,
  onSubmit,
}: {
  status: ApplicationStatus;
  busy: boolean;
  fields: FieldMessages;
  onSubmit: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const back = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (confirming) back.current?.focus();
  }, [confirming]);
  // The phase follows the state, as the server records it: review → preliminary, document stage → final.
  const preliminary = status === "MANUAL_REVIEW";
  function submit(event: FormEvent) {
    event.preventDefault();
    if (reason.trim()) setConfirming(true);
  }
  return (
    <form className="decision-form" onSubmit={submit} noValidate>
      <h3>{preliminary ? "Предварительный отказ" : "Окончательный отказ"}</h3>
      <p className="field-note">
        {preliminary
          ? "Отказ до этапа документов по результатам рассмотрения."
          : "Отказ на этапе документов: полный комплект или принятые документы для него не нужны."}{" "}
        Заявка закроется, клиент увидит причину.
      </p>
      <ReasonField
        id="reject-reason"
        label="Причина отказа"
        hint="Сохранится в истории заявки и будет видна клиенту."
        value={reason}
        error={fields.reason}
        disabled={busy}
        onChange={setReason}
      />
      {!confirming ? (
        <button
          type="submit"
          className="button danger"
          disabled={busy || !reason.trim()}
        >
          Отказать
        </button>
      ) : (
        <div
          className="cancel-confirm"
          role="group"
          aria-labelledby="reject-confirm-title"
        >
          <h4 id="reject-confirm-title">Отказать по заявке?</h4>
          <p>
            Отказ нельзя отменить: заявка закроется, для продолжения клиенту
            понадобится новая.
          </p>
          <div className="form-actions">
            <button
              ref={back}
              type="button"
              className="button secondary"
              disabled={busy}
              onClick={() => setConfirming(false)}
            >
              Вернуться
            </button>
            <button
              type="button"
              className="button danger"
              disabled={busy || !reason.trim()}
              onClick={() => onSubmit(reason.trim())}
            >
              {busy ? "Отправляем…" : "Да, отказать"}
            </button>
          </div>
        </div>
      )}
    </form>
  );
}
