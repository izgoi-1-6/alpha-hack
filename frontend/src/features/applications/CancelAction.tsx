import { useEffect, useId, useRef, useState } from "react";
import { Application, applicationsApi } from "../../api";
import { Icon } from "../../components";
import { CommandAttempts } from "./commands";
import { useCommand } from "./useCommand";

/** Cancellation is final, so it always asks for confirmation and a short reason (the API requires one). */
export function CancelAction({
  application,
  attempts,
  reload,
  announce,
  onCancelled,
  onUnauthorized,
}: {
  application: Pick<Application, "id" | "version">;
  attempts: CommandAttempts;
  reload: () => Promise<unknown>;
  announce: (text: string) => void;
  /** Runs after the cancelled application has been reloaded (e.g. to move focus to the new status). */
  onCancelled?: () => void;
  onUnauthorized: () => void;
}) {
  const command = useCommand(attempts, onUnauthorized);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const trigger = useRef<HTMLButtonElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const restoreFocus = useRef(false);
  const id = useId();
  useEffect(() => {
    if (open) field.current?.focus();
    else if (restoreFocus.current) {
      restoreFocus.current = false;
      trigger.current?.focus();
    }
  }, [open]);

  function close() {
    restoreFocus.current = true;
    command.setProblem(null);
    setOpen(false);
  }
  async function confirm() {
    const body = { version: application.version, reason: reason.trim() };
    const result = await command.run(
      "cancel",
      `cancel:${application.id}`,
      body,
      (key) => applicationsApi.cancel(application.id, body, key),
    );
    if (!result) return;
    if (result.ok) {
      announce("Заявка отменена.");
      await reload();
      onCancelled?.();
    } else if (["version", "status"].includes(result.problem.kind))
      await reload();
  }

  if (!open)
    return (
      <button
        ref={trigger}
        type="button"
        className="button secondary cancel-trigger"
        onClick={() => setOpen(true)}
      >
        Отменить заявку
      </button>
    );
  return (
    <div
      className="cancel-confirm"
      role="group"
      aria-labelledby={id + "-title"}
    >
      <h3 id={id + "-title"}>Отменить заявку?</h3>
      <p>
        Отменённую заявку нельзя возобновить: чтобы продолжить, понадобится
        новая из подбора.
      </p>
      <label htmlFor={id + "-reason"}>Причина отмены</label>
      <textarea
        id={id + "-reason"}
        ref={field}
        rows={2}
        maxLength={2000}
        value={reason}
        disabled={!!command.busy}
        onChange={(event) => setReason(event.target.value)}
        placeholder="Например, выбрали другой продукт"
      />
      {command.problem && (
        <div className="notice error" role="alert">
          <Icon name="info" />
          <span>
            {command.problem.kind === "network"
              ? "Нет связи с сервером. Заявка могла уже отмениться: повторите — повтор не отменит её дважды."
              : command.problem.message}
          </span>
        </div>
      )}
      <div className="form-actions">
        <button
          type="button"
          className="button secondary"
          onClick={close}
          disabled={!!command.busy}
        >
          Не отменять
        </button>
        <button
          type="button"
          className="button danger"
          disabled={!reason.trim() || !!command.busy}
          onClick={() => void confirm()}
        >
          {command.busy ? "Отменяем…" : "Да, отменить заявку"}
        </button>
      </div>
    </div>
  );
}
