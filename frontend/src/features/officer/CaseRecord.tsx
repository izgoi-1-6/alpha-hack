import { AnswerValue, Answers } from "../../api";
import { answerAt, formatDay } from "../applications/fields";
import {
  formatDateTime,
  keepAmountsTogether,
  rub,
} from "../applications/format";
import { OfficerDecision, StaffInfoRequest } from "./officerApi";
import { answerLabel, DECISION_ACTION, PHASE } from "./officerFormat";

const SOURCE_NAME = { registry: "реестр", turnover: "обороты", bki: "БКИ" };
const ENUMS: Record<string, string> = {
  OSN: "ОСН",
  USN: "УСН",
  PSN: "ПСН",
  OTHER: "другой режим",
  declared: "заявлен",
  none: "нет",
  unknown: "не знаю",
};

/** The current answer at a path, in plain words (the pledge as its short summary). */
function answerText(path: string, value: AnswerValue | undefined): string {
  if (value === null || value === undefined || value === "") return "не указано";
  if (typeof value === "boolean") return value ? "да" : "нет";
  if (typeof value === "number")
    return path.endsWith("_rub") ? rub(value) : String(value);
  if (typeof value === "object")
    return (
      [
        value.status && ENUMS[value.status],
        value.declared_value_rub != null && rub(value.declared_value_rub),
        value.description,
      ]
        .filter(Boolean)
        .join(" · ") || "не указано"
    );
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return formatDay(value);
  return ENUMS[value] ?? value;
}

function requestState(request: StaffInfoRequest) {
  if (request.open) return { label: "Открыт", tone: "warning" };
  if (request.resolved_at)
    return {
      label: `Закрыт ${formatDateTime(request.resolved_at)}`,
      tone: "success",
    };
  // An unresolved request of a terminal application is an audit row, never something to act on.
  return { label: "Не завершён: заявка закрыта", tone: "neutral" };
}

/** Every information request, newest first: who asked, what, the client's response and the current answers. */
export function InfoRequestsPanel({
  requests,
  answers,
}: {
  requests: StaffInfoRequest[];
  answers: Answers;
}) {
  return (
    <section className="card record-card" aria-labelledby="requests-heading">
      <div className="panel-title">
        <h2 id="requests-heading">Запросы сведений</h2>
      </div>
      {requests.length === 0 ? (
        <p className="muted">Запросов по заявке не было.</p>
      ) : (
        <ol className="record-list">
          {[...requests].reverse().map((request) => {
            const state = requestState(request);
            return (
              <li key={request.id}>
                <div className="record-head">
                  <strong>
                    {request.kind === "trusted_source"
                      ? `Повторный запрос к источнику: ${request.source ? SOURCE_NAME[request.source] : "источник"}`
                      : request.officer
                        ? `Запрос специалиста · ${request.officer.display_name}`
                        : "Запрос системы"}
                  </strong>
                  <span className={"status " + state.tone}>{state.label}</span>
                </div>
                <p>{keepAmountsTogether(request.question)}</p>
                {request.requested_fields.length > 0 && (
                  <dl className="record-fields">
                    {request.requested_fields.map((path) => (
                      <div key={path}>
                        <dt>{answerLabel(path)}</dt>
                        <dd>
                          сейчас в анкете:{" "}
                          {answerText(path, answerAt(answers, path))}
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
                {request.response && (
                  <blockquote className="client-response">
                    <b>
                      Ответ клиента
                      {request.responded_at
                        ? ` · ${formatDateTime(request.responded_at)}`
                        : ""}
                    </b>
                    <p>{request.response}</p>
                  </blockquote>
                )}
                <small>Создан {formatDateTime(request.created_at)}</small>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

const decisionTitle = (decision: OfficerDecision) =>
  decision.action === "reject"
    ? `${DECISION_ACTION.reject} · ${PHASE[decision.phase]}`
    : decision.amount_rub !== null
      ? `${DECISION_ACTION[decision.action]} · ${rub(decision.amount_rub)}`
      : DECISION_ACTION[decision.action];

/** Officer decisions in order of record, newest first, each with its reason and author. */
export function DecisionsPanel({
  decisions,
  userId,
}: {
  decisions: OfficerDecision[];
  userId: string;
}) {
  return (
    <section className="card record-card" aria-labelledby="decisions-heading">
      <div className="panel-title">
        <h2 id="decisions-heading">Решения специалиста</h2>
      </div>
      {decisions.length === 0 ? (
        <p className="muted">Решений по заявке пока нет.</p>
      ) : (
        <ol className="record-list">
          {[...decisions].reverse().map((decision) => (
            <li key={decision.id}>
              <div className="record-head">
                <strong>{decisionTitle(decision)}</strong>
                <time dateTime={decision.created_at}>
                  {formatDateTime(decision.created_at)}
                </time>
              </div>
              <p>{decision.reason}</p>
              <small>
                {decision.officer.id === userId
                  ? "Вы"
                  : decision.officer.display_name}
              </small>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
