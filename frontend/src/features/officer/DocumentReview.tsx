import { useId, useRef, useState } from "react";
import { DocumentType } from "../../api";
import { DemoBadge, Icon } from "../../components";
import { CommandAttempts } from "../applications/commands";
import { keepAmountsTogether, rub } from "../applications/format";
import { useCommand } from "../applications/useCommand";
import { DocumentFile } from "../documents/DocumentFile";
import {
  DOCUMENT_HINT,
  documentStatus,
  documentTitle,
  formatMoment,
} from "../documents/documentFormat";
import { DocumentReviewForm, ReviewBody } from "./DocumentReviewForm";
import { officerApi, StaffApplication, StaffDocument } from "./officerApi";
import "../documents/documents.css";

const CURRENT = ["UPLOADED", "ACCEPTED", "REJECTED"];

/** Who reviewed a revision, when, why, and the verified value of an accepted valuation. */
function ReviewRecord({ document, userId }: { document: StaffDocument; userId: string }) {
  if (!document.reviewed_at) return null;
  const rejected = document.status === "REJECTED" || document.status === "SUPERSEDED";
  return (
    <div className={"review-note " + (rejected ? "rejected" : "accepted")}>
      <b>
        {rejected ? "Отклонён" : "Принят"}
        {document.reviewer
          ? ` · ${document.reviewer.id === userId ? "Вы" : document.reviewer.display_name}`
          : ""}
        {` · ${formatMoment(document.reviewed_at)}`}
      </b>
      {document.review_reason && <p>{keepAmountsTogether(document.review_reason)}</p>}
      {document.verified_value_rub !== null && (
        <p>Проверенная стоимость залога: {rub(document.verified_value_rub)}</p>
      )}
    </div>
  );
}

function ReviewRow({
  type,
  revisions,
  application,
  userId,
  canReview,
  locked,
  onBusy,
  attempts,
  reload,
  announce,
  onUnauthorized,
}: {
  type: DocumentType;
  /** Every revision of this requirement, oldest first. */
  revisions: StaffDocument[];
  application: StaffApplication;
  userId: string;
  canReview: boolean;
  /** Another document's review is in flight: it will change the version, so this one waits. */
  locked: boolean;
  onBusy: (busy: boolean) => void;
  attempts: CommandAttempts;
  reload: () => Promise<unknown>;
  announce: (text: string) => void;
  onUnauthorized: () => void;
}) {
  const command = useCommand(attempts, onUnauthorized);
  const heading = useRef<HTMLHeadingElement>(null);
  const id = useId();
  const current = revisions.find((document) => CURRENT.includes(document.status));
  const earlier = revisions.filter((document) => document !== current).reverse();
  const status = current ? documentStatus(current.status, application.status) : null;
  const title = documentTitle(type);

  async function review(body: ReviewBody) {
    if (!current) return;
    const sent = { version: application.version, ...body };
    onBusy(true);
    try {
      const result = await command.run(
        "review",
        `officer-review:${current.id}`,
        sent,
        (key) => officerApi.reviewDocument(application.id, current.id, sent, key),
      );
      if (!result) return;
      if (result.ok) {
        announce(
          body.decision === "accept"
            ? `Документ «${title}» принят.`
            : `Документ «${title}» отклонён: комплект возвращён клиенту на замену.`,
        );
        await reload();
        heading.current?.focus();
      } else if (["version", "status"].includes(result.problem.kind)) await reload();
    } finally {
      onBusy(false);
    }
  }

  return (
    <li className="requirement" data-document-type={type} aria-labelledby={id + "-title"}>
      <div className="requirement-head">
        <span className="requirement-icon" aria-hidden="true">
          <Icon name="file" size={20} />
        </span>
        <div className="requirement-title">
          <h3 id={id + "-title"} ref={heading} tabIndex={-1}>
            {title}
          </h3>
          <p>{DOCUMENT_HINT[type]}</p>
        </div>
        <span className={"status requirement-status " + (status?.tone ?? "warning")}>
          {status?.label ?? "Не загружен"}
        </span>
      </div>
      {current ? (
        <DocumentFile document={current} className="requirement-file" showHash />
      ) : (
        <p className="muted">Клиент ещё не загрузил файл.</p>
      )}
      {current && <ReviewRecord document={current} userId={userId} />}
      {canReview && current?.status === "UPLOADED" && (
        <DocumentReviewForm
          key={current.id}
          document={current}
          busy={!!command.busy || locked}
          fields={command.problem?.fields ?? {}}
          onSubmit={(body) => void review(body)}
        />
      )}
      {command.problem && (
        <div className="notice error" role="alert">
          <Icon name="info" />
          <span>
            {command.problem.kind === "network"
              ? "Нет связи с сервером. Решение могло уже сохраниться: повторите — повтор с тем же ключом не запишет его дважды."
              : command.problem.kind === "version"
                ? "Заявка изменилась после загрузки страницы: мы показали актуальную версию."
                : command.problem.message}
          </span>
        </div>
      )}
      {earlier.length > 0 && (
        <details className="requirement-history">
          <summary>Прежние версии ({earlier.length})</summary>
          <ol>
            {earlier.map((document) => (
              <li key={document.id}>
                <span className="status neutral">
                  {documentStatus(document.status, application.status).label}
                </span>
                <DocumentFile document={document} className="history-file" showHash />
                <ReviewRecord document={document} userId={userId} />
              </li>
            ))}
          </ol>
        </details>
      )}
    </li>
  );
}

/**
 * «Документы клиента» on the review page: per requirement, the current file and every earlier revision with its
 * metadata (name, type, size, SHA-256 short form, upload time), downloads through the authorized route, and — for the
 * assignee while the packet is under review — accept or reject with a reason. Labelled with the server's notice.
 */
export function DocumentReview({
  documents,
  notice,
  application,
  userId,
  attempts,
  reload,
  announce,
  onUnauthorized,
}: {
  documents: StaffDocument[];
  notice: string;
  application: StaffApplication;
  userId: string;
  attempts: CommandAttempts;
  reload: () => Promise<unknown>;
  announce: (text: string) => void;
  onUnauthorized: () => void;
}) {
  const types = (application.product.required_documents ??
    [...new Set(documents.map((document) => document.document_type))]) as DocumentType[];
  const canReview = application.allowed_actions.includes("review_document");
  // One review at a time: each raises the version, and the next is sent with the reloaded one.
  const [reviewing, setReviewing] = useState(false);
  const open = application.status === "PREAPPROVED" || application.status === "DOCS_REWORK";
  return (
    <section className="card evidence-card documents-review" aria-labelledby="documents-review-heading">
      <div className="panel-title">
        <h2 id="documents-review-heading">Документы клиента</h2>
        <DemoBadge label="Демонстрационная проверка документов" />
      </div>
      <p className="panel-note">{notice}</p>
      {open && (
        <p className="field-note">
          Комплект у клиента: документы проверяют, когда он отправит комплект.
        </p>
      )}
      <ol className="requirement-list">
        {types.map((type) => (
          <ReviewRow
            key={type}
            type={type}
            revisions={documents.filter((document) => document.document_type === type)}
            application={application}
            userId={userId}
            canReview={canReview}
            locked={reviewing}
            onBusy={setReviewing}
            attempts={attempts}
            reload={reload}
            announce={announce}
            onUnauthorized={onUnauthorized}
          />
        ))}
      </ol>
    </section>
  );
}
