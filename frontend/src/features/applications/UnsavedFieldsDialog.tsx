import { useEffect, useId, useRef } from "react";
import { Icon } from "../../components";
import { keepAmountsTogether } from "./format";

/**
 * Asked before moving on (another stage, or out of the questionnaire) while a value cannot be saved: the customer
 * either stays to fix it or moves on without that value. Nothing invalid is ever dropped silently.
 */
export function UnsavedFieldsDialog({
  fields,
  onStay,
  onProceed,
}: {
  fields: { path: string; label: string; message: string }[];
  onStay: () => void;
  onProceed: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const stay = useRef<HTMLButtonElement>(null);
  const id = useId();
  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) element.showModal();
    stay.current?.focus();
    return () => element?.close();
  }, []);
  const several = fields.length > 1;
  return (
    <dialog
      ref={dialog}
      className="unsaved-dialog"
      aria-labelledby={id + "-title"}
      aria-describedby={id + "-text"}
      onCancel={(event) => {
        // Escape means "stay": the value stays in the form.
        event.preventDefault();
        onStay();
      }}
    >
      <div className="unsaved-dialog-head">
        <Icon name="info" />
        <h2 id={id + "-title"}>
          {several
            ? "Некоторые значения нельзя сохранить"
            : "Это значение нельзя сохранить"}
        </h2>
      </div>
      <ul>
        {fields.map((field) => (
          <li key={field.path}>
            <b>{field.label}</b>: {keepAmountsTogether(field.message)}
          </li>
        ))}
      </ul>
      <p id={id + "-text"}>
        Исправьте {several ? "их" : "его"} или продолжите без{" "}
        {several ? "этих значений" : "этого значения"}: остальные изменения шага
        сохранятся.
      </p>
      <div className="unsaved-dialog-actions">
        <button
          ref={stay}
          type="button"
          className="button primary"
          onClick={onStay}
        >
          Остаться и исправить
        </button>
        <button type="button" className="button secondary" onClick={onProceed}>
          {several
            ? "Перейти, не сохраняя эти поля"
            : "Перейти, не сохраняя это поле"}
        </button>
      </div>
    </dialog>
  );
}
