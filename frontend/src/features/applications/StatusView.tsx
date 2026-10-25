import { useEffect, useId, useRef, useState } from "react";
import { Application, applicationsApi, HistoryItem } from "../../api";
import { DemoBadge, Icon } from "../../components";
import { CancelAction } from "./CancelAction";
import { CommandAttempts } from "./commands";
import {
  documentList,
  formatDate,
  formatDateTime,
  keepAmountsTogether,
  nextStep,
  productName,
  rub,
  STATUS,
} from "./format";
import { Timeline } from "./Timeline";
import { useCommand } from "./useCommand";

const RISK = {
  low: "низкий риск",
  medium: "средний риск",
  high: "высокий риск",
};
const points = (n: number) => {
  const tail = n % 100;
  const last = n % 10;
  const word =
    tail >= 11 && tail <= 14
      ? "баллов"
      : last === 1
        ? "балл"
        : last >= 2 && last <= 4
          ? "балла"
          : "баллов";
  return `${n} ${word}`;
};

/** What the customer can expect and do now, in plain language; never reads as a final approval. */
function explanation(application: Application) {
  const request = application.open_info_request;
  switch (application.status) {
    case "CHECKING":
      return "Проверка демо-источников и скоринг ещё идут. Обновите страницу через несколько секунд.";
    case "WAIT_EXTERNAL":
      return "Один из демо-источников не ответил, поэтому решение пока не принято. Нажмите «Повторить проверку»: запрос выполнится по согласию, которое вы уже дали.";
    case "NEED_INFO":
      return request?.kind === "trusted_source"
        ? "Демо-источник ответил не полностью. Эти сведения нельзя указать в анкете — их даёт только источник. Нажмите «Повторить проверку»."
        : "Для продолжения нужны дополнительные сведения по анкете.";
    case "MANUAL_REVIEW":
      return "Заявку рассмотрит кредитный специалист: решение и возможная сумма определятся после проверки. Пока это не одобрение.";
    case "PREAPPROVED":
      return `${nextStep(application)}: ${documentList(application.product.required_documents)}. Загрузка документов появится на следующем этапе демо. Предварительное одобрение — не окончательное решение: итоговую сумму подтвердит специалист после проверки документов.`;
    case "DOCS_UPLOADED":
      return "Документы переданы на проверку кредитному специалисту.";
    case "DOCS_REWORK":
      return "Часть документов нужно заменить.";
    case "APPROVED":
      return "Это демонстрационное решение: деньги не перечисляются, договор не подписывается.";
    case "REJECTED":
      return "Причина — в результате проверки ниже. Можно подобрать другой продукт или изменить параметры.";
    case "CANCELLED":
      return "Заявка отменена и больше не рассматривается. Новую заявку можно начать из подбора.";
    case "EXPIRED":
      return "Срок предварительного одобрения (14 дней) истёк. Для продолжения создайте новую заявку из подбора.";
    default:
      return nextStep(application);
  }
}

function Amount({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note: string;
  tone?: string;
}) {
  const id = useId();
  return (
    <div
      className={"card amount" + (tone ? " " + tone : "")}
      role="group"
      aria-labelledby={id}
    >
      <span id={id}>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  );
}

export function StatusView({
  application,
  history,
  attempts,
  reload,
  announce,
  focusOnMount,
  onOpenList,
  onRecommend,
  onUnauthorized,
}: {
  application: Application;
  history: HistoryItem[];
  attempts: CommandAttempts;
  reload: () => Promise<unknown>;
  announce: (text: string) => void;
  focusOnMount: boolean;
  onOpenList: () => void;
  onRecommend: (companyId: string) => void;
  onUnauthorized: () => void;
}) {
  const command = useCommand(attempts, onUnauthorized);
  const heading = useRef<HTMLHeadingElement>(null);
  const [focusRequest, setFocusRequest] = useState(focusOnMount ? 1 : 0);
  useEffect(() => {
    if (focusRequest) heading.current?.focus();
  }, [focusRequest]);

  const meta = STATUS[application.status];
  const actions = application.allowed_actions;
  const evaluation = application.latest_evaluation;
  const request = application.open_info_request;
  const terminal = ["REJECTED", "CANCELLED", "EXPIRED"].includes(
    application.status,
  );
  const term = application.answers.term_months;

  async function retry() {
    const body = { version: application.version };
    const result = await command.run(
      "retry",
      `retry:${application.id}`,
      body,
      (key) => applicationsApi.retryCheck(application.id, body, key),
    );
    if (!result) return;
    if (result.ok) {
      announce(
        `Проверка завершена. Статус: ${STATUS[result.value.application.status].label}.`,
      );
      await reload();
      setFocusRequest((n) => n + 1);
    } else if (["version", "status"].includes(result.problem.kind))
      await reload();
  }

  return (
    <div className="status-page">
      <button type="button" className="back-button" onClick={onOpenList}>
        ← Мои заявки
      </button>
      <div className="page-heading status-heading">
        <div>
          <div className="eyebrow accent">
            Заявка · {productName(application)}
          </div>
          <h1 ref={heading} tabIndex={-1}>
            {meta.headline}
          </h1>
          <p>
            {application.company.name} · ИНН {application.company.inn} ·{" "}
            {application.submitted_at
              ? `отправлена ${formatDate(application.submitted_at)}`
              : `создана ${formatDate(application.created_at)}`}
          </p>
        </div>
        <span className={"status status-pill " + meta.tone}>{meta.label}</span>
      </div>

      <section className="card status-next" aria-labelledby="next-heading">
        <h2 id="next-heading">Что дальше</h2>
        <p>{explanation(application)}</p>
        {request && (
          <div className="info-request">
            <b>
              {request.requested_by === "system"
                ? "Запрос системы"
                : "Запрос кредитного специалиста"}
            </b>
            <p>{keepAmountsTogether(request.question)}</p>
            {request.kind === "client_answers" && (
              <p>Ответить на запрос можно будет на следующем этапе демо.</p>
            )}
          </div>
        )}
        {command.problem && (
          <div className="notice error" role="alert">
            <Icon name="info" />
            <span>
              {command.problem.kind === "network"
                ? "Нет связи с сервером. Проверка могла уже выполниться: нажмите «Повторить проверку» ещё раз — повтор не создаст второе решение."
                : command.problem.message}
            </span>
          </div>
        )}
        {(actions.includes("retry_check") ||
          actions.includes("cancel") ||
          terminal) && (
          <div className="status-actions">
            {actions.includes("retry_check") && (
              <button
                type="button"
                className="button primary"
                onClick={() => void retry()}
                disabled={!!command.busy}
              >
                <Icon name="refresh" size={17} />
                {command.busy ? "Проверяем…" : "Повторить проверку"}
              </button>
            )}
            {actions.includes("cancel") && (
              <CancelAction
                application={application}
                attempts={attempts}
                reload={reload}
                announce={announce}
                onCancelled={() => setFocusRequest((n) => n + 1)}
                onUnauthorized={onUnauthorized}
              />
            )}
            {terminal && (
              <button
                type="button"
                className="button secondary"
                onClick={() => onRecommend(application.company_id)}
              >
                Подобрать финансирование
              </button>
            )}
          </div>
        )}
      </section>

      <div className="amounts">
        <Amount
          label="Запрошенная сумма"
          value={
            application.requested_amount_rub !== null
              ? rub(application.requested_amount_rub)
              : "Не указана"
          }
          note={`${typeof term === "number" ? `Срок ${term} мес. ` : ""}Исходная сумма заявки не меняется.`}
        />
        {application.status !== "REJECTED" && (
          <Amount
            label="Предварительная оценка лимита"
            value={
              application.indicative_limit_rub !== null
                ? rub(application.indicative_limit_rub)
                : "Не рассчитана"
            }
            note="Ориентир по обороту — не предложение и не решение банка."
          />
        )}
        {application.preapproved_amount_rub !== null && (
          <Amount
            label="Предварительно одобрено"
            tone="preapproved"
            value={rub(application.preapproved_amount_rub)}
            note={`Это не окончательное решение и не обещание выдачи.${application.preapproval_expires_at ? ` Действует до ${formatDate(application.preapproval_expires_at)}` : ""}`}
          />
        )}
        {application.final_amount_rub !== null && (
          <Amount
            label="Итоговая сумма (демо-решение)"
            value={rub(application.final_amount_rub)}
            note="Демонстрационное решение: деньги не перечисляются."
          />
        )}
      </div>

      <div className="status-layout">
        <section
          className="card status-result"
          aria-labelledby="result-heading"
        >
          <div className="panel-title">
            <h2 id="result-heading">Результат проверки</h2>
            <DemoBadge />
          </div>
          {evaluation ? (
            <>
              <ul className="result-reasons">
                {evaluation.reasons.map((reason) => (
                  <li key={reason}>{keepAmountsTogether(reason)}</li>
                ))}
              </ul>
              <dl className="result-meta">
                {evaluation.score !== null && (
                  <div>
                    <dt>Демо-скоринг</dt>
                    <dd>
                      {points(evaluation.score)}
                      {evaluation.risk ? ` · ${RISK[evaluation.risk]}` : ""}
                    </dd>
                  </div>
                )}
                {evaluation.scored_limit_rub !== null && (
                  <div>
                    <dt>Расчётный лимит по проверке</dt>
                    <dd>
                      {rub(evaluation.scored_limit_rub)}
                      <small>
                        Расчёт демо-скоринга — не предложение и не решение
                        банка.
                      </small>
                    </dd>
                  </div>
                )}
                <div>
                  <dt>Проверено</dt>
                  <dd>{formatDateTime(evaluation.created_at)}</dd>
                </div>
              </dl>
            </>
          ) : (
            <p className="muted">Проверка по этой заявке не проводилась.</p>
          )}
        </section>
        <Timeline items={history} />
      </div>
      <div className="notice quiet">
        <Icon name="shield" />
        <span>
          Реестр, обороты, БКИ и уведомления — локальные имитации. Решения
          демонстрационные: договор не подписывается, деньги не перечисляются.
        </span>
      </div>
    </div>
  );
}
