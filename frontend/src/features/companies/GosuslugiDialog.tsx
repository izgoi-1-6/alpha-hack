import { useEffect, useId, useRef, useState } from "react";
import { api, AuthorityVerification } from "../../api";
import { Icon } from "../../components";
import { CommandAttempts } from "../applications/commands";
import { useCommand } from "../applications/useCommand";
import "./onboarding.css";

const minutesBetween = (from: string, to: string) =>
  Math.round((Date.parse(to) - Date.parse(from)) / 60000);

/**
 * The Госуслуги confirmation of the representative for one ИНН. Opening it asks the check for the person and the
 * role; the customer sees them with the company and confirms, or closes the dialog (Escape, «Отмена») without a
 * confirmation — an unconfirmed check simply expires. A lost response is repeated with the same key. Neutral styling:
 * no logo, colours or marks of the real service.
 */
export function GosuslugiDialog({
  inn,
  companyName,
  onConfirm,
  onClose,
  onUnauthorized,
}: {
  inn: string;
  /** The registry name of the chosen company, when the ИНН is one of the listed companies. */
  companyName: string | null;
  onConfirm: (verification: AuthorityVerification) => void;
  onClose: () => void;
  onUnauthorized: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const confirm = useRef<HTMLButtonElement>(null);
  const retry = useRef<HTMLButtonElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const id = useId();
  // One dialog is one check: its keys live as long as the dialog does.
  const attempts = useRef<CommandAttempts>(new Map());
  const command = useCommand(attempts.current, onUnauthorized);
  const [verification, setVerification] =
    useState<AuthorityVerification | null>(null);

  async function check() {
    const body = { inn };
    const result = await command.run(
      "verify",
      `gosuslugi:${inn}`,
      body,
      (key) => api.verifyAuthority(inn, key),
    );
    if (result?.ok) setVerification(result.value);
  }
  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) element.showModal();
    void check();
    return () => element?.close();
  }, []);
  // Focus follows the state: «Отмена» while checking, «Подтвердить» once the person is known, «Повторить» after a
  // failure.
  useEffect(() => {
    (verification
      ? confirm
      : command.problem
        ? retry
        : cancel
    ).current?.focus();
  }, [verification, command.problem]);

  return (
    <dialog
      ref={dialog}
      className="gosuslugi-dialog"
      aria-labelledby={id + "-title"}
      aria-describedby={id + "-text"}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className="gosuslugi-head">
        <span className="gosuslugi-mark" aria-hidden="true">
          <Icon name="shield" size={22} />
        </span>
        <div>
          <h2 id={id + "-title"}>Подтверждение полномочий через Госуслуги</h2>
          <p id={id + "-text"}>
            Госуслуги передают ФИО и должность представителя компании. Проверьте
            сведения и подтвердите, что действуете от имени компании.
          </p>
        </div>
      </div>
      <dl className="gosuslugi-facts">
        <div>
          <dt>Компания</dt>
          <dd>{companyName ?? "Компания по ИНН"}</dd>
        </div>
        <div>
          <dt>ИНН</dt>
          <dd className="mono">{inn}</dd>
        </div>
        {verification && (
          <>
            <div>
              <dt>Представитель</dt>
              <dd>{verification.person_name}</dd>
            </div>
            <div>
              <dt>Должность</dt>
              <dd>{verification.role}</dd>
            </div>
          </>
        )}
      </dl>
      {command.busy && (
        <p className="gosuslugi-loading" role="status">
          <span className="spinner" aria-hidden="true" />
          Получаем сведения из Госуслуг…
        </p>
      )}
      {verification && (
        <p className="gosuslugi-note">
          Подтверждение действует{" "}
          {minutesBetween(verification.verified_at, verification.expires_at)}{" "}
          мин.: за это время добавьте компанию.
        </p>
      )}
      {command.problem && (
        <div className="notice error" role="alert">
          <Icon name="info" />
          <span>{command.problem.message}</span>
        </div>
      )}
      <div className="gosuslugi-actions">
        {verification && (
          <button
            ref={confirm}
            type="button"
            className="button primary"
            onClick={() => onConfirm(verification)}
          >
            Подтвердить
          </button>
        )}
        {command.problem && (
          <button
            ref={retry}
            type="button"
            className="button primary"
            onClick={() => void check()}
          >
            <Icon name="refresh" size={17} />
            Повторить
          </button>
        )}
        <button
          ref={cancel}
          type="button"
          className="button secondary"
          onClick={onClose}
        >
          Отмена
        </button>
      </div>
    </dialog>
  );
}
