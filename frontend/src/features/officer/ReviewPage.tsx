import { useEffect, useRef, useState } from "react";
import { ApiError, errorMessage } from "../../api";
import { ErrorNotice, Icon, Loading } from "../../components";
import { CommandAttempts } from "../applications/commands";
import { formatDate, productName, STATUS } from "../applications/format";
import { Timeline } from "../applications/Timeline";
import { DecisionsPanel, InfoRequestsPanel } from "./CaseRecord";
import { DecisionPanel } from "./DecisionPanel";
import { officerApi, StaffDetail, StaffHistoryItem } from "./officerApi";
import { shortId } from "./officerFormat";
import { EvaluationsPanel, ReviewAmounts, ScorePanel } from "./ScoreEvidence";
import { FinancePanel, SourcesPanel } from "./SourceEvidence";
import "../applications/applications.css";
import "./officer.css";

/**
 * `?application=<id>` for a CREDIT_OFFICER: the evidence, the record of requests and decisions, and the decision
 * controls. Reads are revisioned and aborted when superseded; a reload after a command keeps the page (and the
 * typed decision forms) mounted, and only the first read shows a loading state.
 */
export function ReviewPage({
  applicationId,
  userId,
  attempts,
  onOpenQueue,
  onUnauthorized,
}: {
  applicationId: string;
  userId: string;
  attempts: CommandAttempts;
  onOpenQueue: () => void;
  onUnauthorized: () => void;
}) {
  const [detail, setDetail] = useState<StaffDetail | null>(null);
  const [failure, setFailure] = useState<{
    notFound: boolean;
    message: string;
  } | null>(null);
  const [notice, setNotice] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const revision = useRef(0);
  const reader = useRef<AbortController | null>(null);
  const shown = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    void load();
    return () => {
      revision.current += 1;
      reader.current?.abort();
    };
  }, []);

  async function load() {
    const mine = ++revision.current;
    reader.current?.abort();
    const controller = new AbortController();
    reader.current = controller;
    const current = () =>
      mine === revision.current && !controller.signal.aborted;
    try {
      const next = await officerApi.detail(applicationId, controller.signal);
      if (!current()) return;
      shown.current = true;
      setDetail(next);
      setFailure(null);
      setNotice("");
    } catch (error) {
      if (!current()) return;
      if (error instanceof ApiError && error.status === 401)
        return onUnauthorized();
      const message = errorMessage(error);
      if (shown.current) setNotice(`Не удалось обновить заявку. ${message}`);
      else
        setFailure({
          notFound: error instanceof ApiError && error.status === 404,
          message,
        });
    }
  }

  function announce(text: string) {
    // Clear first so that the same message is announced again.
    setAnnouncement("");
    window.requestAnimationFrame(() => setAnnouncement(text));
  }

  const actorLabel = (item: StaffHistoryItem) =>
    item.actor_role === "system"
      ? "Система · демо-проверка"
      : item.actor_role === "client"
        ? `Клиент · ${item.actor?.display_name ?? "владелец заявки"}`
        : item.actor?.id === userId
          ? "Вы"
          : `Специалист · ${item.actor?.display_name ?? ""}`;

  let content;
  if (failure)
    content = failure.notFound ? (
      <>
        <div className="page-heading">
          <div className="eyebrow accent">Рассмотрение заявки</div>
          <h1>Заявка не найдена</h1>
          <p>Ссылка устарела или содержит ошибку.</p>
        </div>
        <button type="button" className="button primary" onClick={onOpenQueue}>
          Перейти к очереди заявок
          <Icon />
        </button>
      </>
    ) : (
      <ErrorNotice error={failure.message} onRetry={() => void load()} />
    );
  else if (!detail) content = <Loading />;
  else {
    const application = detail.application;
    const meta = STATUS[application.status];
    content = (
      <>
        <button type="button" className="back-button" onClick={onOpenQueue}>
          ← Очередь заявок
        </button>
        <div className="page-heading review-heading">
          <div>
            <div className="eyebrow accent">
              Рассмотрение заявки · № {shortId(application.id)}
            </div>
            <h1 ref={heading} tabIndex={-1}>
              {application.company.name}
            </h1>
            <p>
              {productName(application)} · ИНН {application.company.inn} ·{" "}
              {application.submitted_at
                ? `отправлена ${formatDate(application.submitted_at)}`
                : `черновик от ${formatDate(application.created_at)}`}
            </p>
          </div>
          <span className={"status status-pill " + meta.tone}>
            {meta.label}
          </span>
        </div>
        <ReviewAmounts application={application} />
        <div className="review-layout">
          <div className="review-column">
            <ScorePanel evaluation={detail.evaluations.at(-1)} />
            <SourcesPanel evidence={detail.source_evidence} />
            <FinancePanel finance={detail.source_evidence.finance} />
            <EvaluationsPanel evaluations={detail.evaluations} />
          </div>
          <div className="review-column">
            <DecisionPanel
              application={application}
              userId={userId}
              attempts={attempts}
              reload={load}
              announce={announce}
              onDecided={() => heading.current?.focus()}
              onUnauthorized={onUnauthorized}
            />
            <InfoRequestsPanel
              requests={detail.info_requests}
              answers={application.answers}
            />
            <DecisionsPanel decisions={detail.decisions} userId={userId} />
            <Timeline items={detail.history} actorLabel={actorLabel} />
          </div>
        </div>
        <div className="notice quiet">
          <Icon name="shield" />
          <span>
            Реестр, обороты, БКИ и уведомления — локальные имитации. Решения
            демонстрационные: договор не подписывается, деньги не перечисляются.
          </span>
        </div>
      </>
    );
  }

  return (
    <div className="officer-page review-page">
      <div
        className="sr-only officer-live"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {announcement}
      </div>
      {notice && (
        <div className="notice caution" role="status">
          <Icon name="info" />
          <span>{notice}</span>
        </div>
      )}
      {content}
    </div>
  );
}
