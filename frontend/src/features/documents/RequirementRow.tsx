import { useEffect, useId, useRef, useState } from "react";
import {
  Application,
  ApplicationDocument,
  DocumentChecklist,
} from "../../api";
import { Icon } from "../../components";
import { CommandAttempts, unknownOutcome } from "../applications/commands";
import { keepAmountsTogether, rub } from "../applications/format";
import { useCommand } from "../applications/useCommand";
import { DocumentFile } from "./DocumentFile";
import {
  ACCEPTED_FILES,
  DOCUMENT_HINT,
  documentStatus,
  documentTitle,
  formatMoment,
} from "./documentFormat";
import { documentsApi } from "./documentsApi";
import { UploadJob } from "./useDocumentUploads";

function UploadState({
  job,
  onRetry,
  onDismiss,
}: {
  job: UploadJob;
  onRetry: () => void;
  onDismiss: () => void;
}) {
  const name = job.file.name;
  if (job.phase === "queued")
    return (
      <p className="upload-state">
        В очереди: «{name}» загрузится после текущего файла.
      </p>
    );
  if (job.phase === "uploading") {
    const percent = Math.round(job.progress * 100);
    return (
      <div className="upload-state">
        <span>
          {percent < 100
            ? `Загружаем «${name}»: ${percent} %`
            : `Файл «${name}» получен, идёт проверка…`}
        </span>
        <progress max={100} value={percent} aria-label={`Загрузка файла «${name}»`} />
      </div>
    );
  }
  return (
    <div className="notice error upload-error" role="alert">
      <Icon name="info" />
      <div>
        <p>{job.message}</p>
        <div className="upload-error-actions">
          {job.retry && (
            <button type="button" className="button secondary" onClick={onRetry}>
              Повторить загрузку
            </button>
          )}
          <button type="button" className="text-button" onClick={onDismiss}>
            Скрыть сообщение
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * What the officer decided about the current file: the reason of a rejection, or the note of an acceptance. The
 * request to upload a corrected file appears only while the row can still take one.
 */
function ReviewNote({
  document,
  canUpload,
}: {
  document: ApplicationDocument;
  canUpload: boolean;
}) {
  if (document.status !== "REJECTED" && document.status !== "ACCEPTED") return null;
  const rejected = document.status === "REJECTED";
  return (
    <div className={"review-note " + (rejected ? "rejected" : "accepted")}>
      <b>
        {rejected ? "Причина отклонения" : "Принят кредитным специалистом"}
        {document.reviewed_at ? ` · ${formatMoment(document.reviewed_at)}` : ""}
      </b>
      {document.review_reason && <p>{keepAmountsTogether(document.review_reason)}</p>}
      {document.verified_value_rub !== null && (
        <p>Проверенная стоимость залога: {rub(document.verified_value_rub)}</p>
      )}
      {rejected && canUpload && <p>Загрузите исправленный файл вместо этого.</p>}
    </div>
  );
}

/**
 * One requirement of the checklist: its current file and review, the upload or replacement of an unaccepted file with
 * per-file progress and the server's refusal on this row, deletion (confirmed), and earlier revisions as history.
 */
export function RequirementRow({
  requirement,
  earlier,
  application,
  job,
  done,
  canUpload,
  canDelete,
  locked,
  commandBusy,
  onCommand,
  onChoose,
  onRetry,
  onDismiss,
  attempts,
  reload,
  announce,
  onUnauthorized,
}: {
  requirement: DocumentChecklist["requirements"][number];
  /** Superseded and deleted revisions of this requirement, newest first. */
  earlier: ApplicationDocument[];
  application: Application;
  job?: UploadJob;
  done?: string;
  canUpload: boolean;
  canDelete: boolean;
  /** An upload or a command is running: the version is about to change. */
  locked: boolean;
  /** A command (a deletion here or on another row, or the completion) is running: an upload must wait for it. */
  commandBusy: boolean;
  /** Reports this row's deletion running, for the checklist's shared lock. */
  onCommand: (running: boolean) => void;
  onChoose: (file: File) => void;
  onRetry: () => void;
  onDismiss: () => void;
  attempts: CommandAttempts;
  reload: () => Promise<unknown>;
  announce: (text: string) => void;
  onUnauthorized: () => void;
}) {
  const command = useCommand(attempts, onUnauthorized);
  const [confirming, setConfirming] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  // Focus follows the confirmation, as in CancelAction: into it on opening, back to «Удалить файл» on «Оставить».
  const trigger = useRef<HTMLButtonElement>(null);
  const keep = useRef<HTMLButtonElement>(null);
  const uploadButton = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  useEffect(() => {
    if (confirming) keep.current?.focus();
    else if (restoreFocus.current) {
      restoreFocus.current = false;
      trigger.current?.focus();
    }
  }, [confirming]);
  // After a deletion focus goes to the upload that replaces the file, once the shared lock has let it go.
  const focusUpload = useRef(false);
  useEffect(() => {
    if (focusUpload.current && !commandBusy && !command.busy) {
      focusUpload.current = false;
      uploadButton.current?.focus();
    }
  });
  const type = requirement.document_type;
  const current = requirement.current_document;
  const status = current ? documentStatus(current.status, application.status) : null;
  const sending = job?.phase === "queued" || job?.phase === "uploading";

  async function remove() {
    if (!current) return;
    const body = { version: application.version };
    onCommand(true);
    try {
      const result = await command.run(
        "delete",
        `delete-document:${current.id}`,
        body,
        (key) => documentsApi.remove(application.id, current.id, body, key),
      );
      if (!result) return;
      if (result.ok) {
        setConfirming(false);
        announce(`Файл «${current.original_name}» удалён.`);
        await reload();
        focusUpload.current = true;
        return;
      }
      restoreFocus.current = true;
      setConfirming(false);
      if (["version", "status"].includes(result.problem.kind)) await reload();
    } finally {
      onCommand(false);
    }
  }

  return (
    <li className="requirement" data-document-type={type} aria-labelledby={id + "-title"}>
      <div className="requirement-head">
        <span className="requirement-icon" aria-hidden="true">
          <Icon name="file" size={20} />
        </span>
        <div className="requirement-title">
          <h3 id={id + "-title"}>{documentTitle(type)}</h3>
          <p>
            {requirement.required ? "Обязательный. " : "Необязательный. "}
            {DOCUMENT_HINT[type]}
          </p>
        </div>
        <span className={"status requirement-status " + (status?.tone ?? "warning")}>
          {status?.label ?? "Не загружен"}
        </span>
      </div>
      {current && <DocumentFile document={current} className="requirement-file" />}
      {current && <ReviewNote document={current} canUpload={canUpload} />}
      {job && <UploadState job={job} onRetry={onRetry} onDismiss={onDismiss} />}
      {done && !job && (
        <p className="upload-done">
          <Icon name="check" size={16} />
          {done}
        </p>
      )}
      {command.problem && (
        <div className="notice error" role="alert">
          <Icon name="info" />
          <span>
            {command.problem.kind === "network"
              ? unknownOutcome(
                  command.problem,
                  "Файл мог уже удалиться: повторите — повтор не удалит другой файл.",
                )
              : command.problem.message}
          </span>
        </div>
      )}
      {confirming && current ? (
        <div className="cancel-confirm" role="group" aria-labelledby={id + "-confirm"}>
          <h4 id={id + "-confirm"}>Удалить файл?</h4>
          <p>
            «{current.original_name}» уйдёт из комплекта; при необходимости
            загрузите файл заново.
          </p>
          <div className="form-actions">
            <button
              ref={keep}
              type="button"
              className="button secondary"
              disabled={!!command.busy}
              onClick={() => {
                restoreFocus.current = true;
                setConfirming(false);
              }}
            >
              Оставить
            </button>
            <button
              type="button"
              className="button danger"
              disabled={!!command.busy || locked}
              onClick={() => void remove()}
            >
              {command.busy ? "Удаляем…" : "Да, удалить"}
            </button>
          </div>
        </div>
      ) : (
        (canUpload || canDelete) && (
          <div className="requirement-actions">
            {canUpload && (
              <button
                ref={uploadButton}
                type="button"
                className="button secondary"
                disabled={sending || commandBusy || !!command.busy}
                onClick={() => input.current?.click()}
              >
                <Icon name="upload" size={18} />
                {current ? "Заменить файл" : "Загрузить файл"}
              </button>
            )}
            {canDelete && (
              <button
                ref={trigger}
                type="button"
                className="button secondary"
                disabled={sending || locked || !!command.busy}
                onClick={() => setConfirming(true)}
              >
                Удалить файл
              </button>
            )}
            <input
              ref={input}
              type="file"
              hidden
              accept={ACCEPTED_FILES}
              aria-label={`Файл: ${documentTitle(type)}`}
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) {
                  command.setProblem(null);
                  onChoose(file);
                }
              }}
            />
          </div>
        )
      )}
      {earlier.length > 0 && (
        <details className="requirement-history">
          <summary>Прежние версии ({earlier.length})</summary>
          <ol>
            {earlier.map((document) => (
              <li key={document.id}>
                <span className="status neutral">
                  {/* Only a rejected revision is reviewed before it is replaced: an accepted one never is. */}
                  {document.status === "SUPERSEDED" && document.reviewed_at
                    ? "Отклонён · заменён"
                    : documentStatus(document.status, application.status).label}
                </span>
                <DocumentFile document={document} className="history-file" />
                {document.review_reason && (
                  <p>Комментарий специалиста: {keepAmountsTogether(document.review_reason)}</p>
                )}
              </li>
            ))}
          </ol>
        </details>
      )}
    </li>
  );
}
