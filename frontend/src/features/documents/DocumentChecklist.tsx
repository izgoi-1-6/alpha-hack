import { Application, DocumentChecklist as Checklist } from "../../api";
import { DemoBadge, Icon } from "../../components";
import { CommandAttempts } from "../applications/commands";
import { useCommand } from "../applications/useCommand";
import { documentTitle, formatMoment } from "./documentFormat";
import { documentsApi } from "./documentsApi";
import { RequirementRow } from "./RequirementRow";
import { useDocumentUploads } from "./useDocumentUploads";
import "./documents.css";

const EDITABLE = ["PREAPPROVED", "DOCS_REWORK"];
const DOCUMENT_PHASE = ["PREAPPROVED", "DOCS_UPLOADED", "DOCS_REWORK"];

function packetSummary(application: Application) {
  const summary = application.document_summary;
  if (!summary) return null;
  const parts = [`Загружено ${summary.current_uploaded} из ${summary.required_total}`];
  if (summary.accepted) parts.push(`принято ${summary.accepted}`);
  if (summary.rejected) parts.push(`отклонено ${summary.rejected}`);
  return parts.join(" · ");
}

/**
 * The customer's checklist after preapproval: requirements with their current files, uploads and replacements while
 * the packet is open (PREAPPROVED, DOCS_REWORK), the frozen packet under review (DOCS_UPLOADED) and a read-only record
 * afterwards. «Отправить комплект» appears only when the server's `allowed_actions` offer it. Every command reloads
 * the page, so the next one carries the version the server last returned.
 */
export function DocumentChecklist({
  application,
  checklist,
  attempts,
  reload,
  announce,
  onSubmitted,
  onUnauthorized,
}: {
  application: Application;
  checklist: Checklist;
  attempts: CommandAttempts;
  reload: () => Promise<unknown>;
  announce: (text: string) => void;
  /** Runs after the submitted packet has been reloaded (e.g. to move focus to the new status). */
  onSubmitted: () => void;
  onUnauthorized: () => void;
}) {
  const uploads = useDocumentUploads({ application, attempts, reload, announce, onUnauthorized });
  const command = useCommand(attempts, onUnauthorized);
  const actions = application.allowed_actions;
  const status = application.status;
  const editable = EDITABLE.includes(status);
  const rejected = checklist.requirements
    .filter((row) => row.current_document?.status === "REJECTED")
    .map((row) => documentTitle(row.document_type).toLowerCase());
  const missing = (application.document_summary?.missing ?? []).map((type) =>
    documentTitle(type).toLowerCase(),
  );
  const todo = [
    missing.length > 0 && `загрузите: ${missing.join(", ")}`,
    rejected.length > 0 && `замените отклонённые: ${rejected.join(", ")}`,
  ].filter((part): part is string => !!part);
  const summary = packetSummary(application);

  async function complete() {
    const body = { version: application.version };
    const result = await command.run(
      "complete",
      `complete-documents:${application.id}`,
      body,
      (key) => documentsApi.complete(application.id, body, key),
    );
    if (!result) return;
    if (result.ok) {
      announce("Комплект документов отправлен на проверку.");
      await reload();
      onSubmitted();
    } else if (["version", "status"].includes(result.problem.kind)) await reload();
  }

  return (
    <section className="card documents-card" aria-labelledby="documents-heading">
      <div className="panel-title">
        <h2 id="documents-heading">Документы по заявке</h2>
        <DemoBadge label="Демонстрационная проверка документов" />
      </div>
      <p className="documents-notice">{checklist.notice}</p>
      {DOCUMENT_PHASE.includes(status) && application.preapproval_expires_at && (
        <p className="documents-deadline">
          <Icon name="clock" size={18} />
          <span>
            Предварительное одобрение действует до{" "}
            <b>{formatMoment(application.preapproval_expires_at)}</b>. Загрузка
            и замена документов срок не продлевают.
          </span>
        </p>
      )}
      {status === "DOCS_UPLOADED" && (
        <div className="notice quiet">
          <Icon name="shield" />
          <span>
            Комплект на проверке у кредитного специалиста: пока идёт проверка,
            файлы нельзя заменить или удалить.
          </span>
        </div>
      )}
      {!DOCUMENT_PHASE.includes(status) && (
        <p className="muted">
          Загрузка закрыта: документы сохранены в заявке, их можно скачать.
        </p>
      )}
      {summary && <p className="documents-summary">{summary}</p>}
      <ol className="requirement-list">
        {checklist.requirements.map((requirement) => {
          const type = requirement.document_type;
          const current = requirement.current_document;
          return (
            <RequirementRow
              key={type}
              requirement={requirement}
              earlier={checklist.items
                .filter((item) => item.document_type === type && item.id !== current?.id)
                .reverse()}
              application={application}
              job={uploads.jobs[type]}
              done={uploads.done[type]}
              canUpload={actions.includes("upload_document") && current?.status !== "ACCEPTED"}
              canDelete={
                actions.includes("delete_document") &&
                (current?.status === "UPLOADED" || current?.status === "REJECTED")
              }
              locked={uploads.busy || !!command.busy}
              onChoose={(file) => uploads.choose(type, file)}
              onRetry={() => uploads.retry(type)}
              onDismiss={() => uploads.dismiss(type)}
              attempts={attempts}
              reload={reload}
              announce={announce}
              onUnauthorized={onUnauthorized}
            />
          );
        })}
      </ol>
      {editable && (
        <div className="documents-submit">
          {actions.includes("complete_documents") ? (
            <>
              <p>
                Все обязательные документы на месте. После отправки файлы нельзя
                заменить, пока специалист их не проверит.
              </p>
              <button
                type="button"
                className="button primary"
                disabled={uploads.busy || !!command.busy}
                onClick={() => void complete()}
              >
                {command.busy ? "Отправляем…" : "Отправить комплект"}
              </button>
            </>
          ) : (
            todo.length > 0 && (
              <p className="field-note">Чтобы отправить комплект, {todo.join("; ")}.</p>
            )
          )}
          {command.problem && (
            <div className="notice error" role="alert">
              <Icon name="info" />
              <span>
                {command.problem.kind === "network"
                  ? "Нет связи с сервером. Комплект мог уже отправиться: повторите — повтор не отправит его дважды."
                  : command.problem.message}
              </span>
            </div>
          )}
          <p className="field-note">
            PDF, JPEG или PNG до 20 МБ, по одному файлу на документ. Загружайте
            только синтетические демо-файлы.
          </p>
        </div>
      )}
    </section>
  );
}
