import { MouseEvent, useEffect, useState } from "react";
import { ApiError, ApplicationStatus, errorMessage } from "../../api";
import { ErrorNotice, Icon, Loading } from "../../components";
import {
  formatDateTime,
  productName,
  rub,
  STATUS,
} from "../applications/format";
import {
  AssigneeFilter,
  officerApi,
  QueueFilters,
  StaffApplication,
} from "./officerApi";
import {
  assigneeLabel,
  QUEUE_STATUSES,
  RISK_SHORT,
  shortId,
} from "./officerFormat";
import "../applications/applications.css";
import "./officer.css";

const ASSIGNEE_OPTIONS: { value: AssigneeFilter | ""; label: string }[] = [
  { value: "", label: "Все" },
  { value: "me", label: "Мои" },
  { value: "unassigned", label: "Не назначены" },
];

/** Queue filters live in the address (`status`, `assignee`), so a reload keeps them; unknown values are ignored. */
export function readQueueFilters(params: URLSearchParams): QueueFilters {
  const status = params.get("status") as ApplicationStatus | null;
  const assignee = params.get("assignee");
  return {
    ...(status && QUEUE_STATUSES.includes(status) ? { status } : {}),
    ...(assignee === "me" || assignee === "unassigned" ? { assignee } : {}),
  };
}

export function queueParams(filters: QueueFilters): Record<string, string> {
  const params: Record<string, string> = {};
  if (filters.status) params.status = filters.status;
  if (filters.assignee) params.assignee = filters.assignee;
  return params;
}

const filterKey = (filters: QueueFilters) =>
  `${filters.status ?? ""}|${filters.assignee ?? ""}`;

/** `?view=queue` (an officer's landing page): submitted applications, oldest submission first, in a dense table. */
export function OfficerQueue({
  userId,
  filters,
  onFilter,
  onOpen,
  onUnauthorized,
}: {
  userId: string;
  filters: QueueFilters;
  onFilter: (filters: QueueFilters) => void;
  onOpen: (id: string) => void;
  onUnauthorized: () => void;
}) {
  // Rows are kept with the filters they were read for, so a filter change never shows the previous rows.
  const [loaded, setLoaded] = useState<{
    key: string;
    items: StaffApplication[];
  } | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const key = filterKey(filters);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    officerApi
      .queue(filters, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setLoaded({ key, items: result.items });
      })
      .catch((failure) => {
        if (controller.signal.aborted) return;
        if (failure instanceof ApiError && failure.status === 401)
          onUnauthorized();
        else setError(errorMessage(failure));
      });
    return () => controller.abort();
  }, [key, attempt]);
  const items = loaded?.key === key ? loaded.items : null;
  const filtered = !!(filters.status || filters.assignee);

  // A plain click opens in place; modified clicks keep the browser's own link behaviour.
  const open = (event: MouseEvent<HTMLAnchorElement>, id: string) => {
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    event.preventDefault();
    onOpen(id);
  };

  return (
    <div className="officer-page queue-page">
      <div className="page-heading">
        <div className="eyebrow accent">Кабинет кредитного специалиста</div>
        <h1>Очередь заявок</h1>
        <p>
          Отправленные клиентами заявки — сначала самые ранние. Откройте заявку,
          чтобы проверить данные и принять предварительное решение.
        </p>
      </div>
      <section className="card queue-filters" aria-label="Фильтры очереди">
        <div className="field">
          <label htmlFor="queue-status">Статус</label>
          <select
            id="queue-status"
            value={filters.status ?? ""}
            onChange={(event) =>
              onFilter({
                ...filters,
                status: (event.target.value || undefined) as
                  | ApplicationStatus
                  | undefined,
              })
            }
          >
            <option value="">Все статусы</option>
            {QUEUE_STATUSES.map((status) => (
              <option key={status} value={status}>
                {STATUS[status].label}
              </option>
            ))}
          </select>
        </div>
        <fieldset className="choice-field">
          <legend>Ответственный</legend>
          <div className="choices">
            {ASSIGNEE_OPTIONS.map((option) => {
              const chosen = (filters.assignee ?? "") === option.value;
              return (
                <label
                  key={option.value}
                  className={"choice" + (chosen ? " chosen" : "")}
                >
                  <input
                    type="radio"
                    name="queue-assignee"
                    value={option.value}
                    checked={chosen}
                    onChange={() =>
                      onFilter({
                        ...filters,
                        assignee: option.value || undefined,
                      })
                    }
                  />
                  <span>{option.label}</span>
                </label>
              );
            })}
          </div>
        </fieldset>
        {filtered && (
          <button
            type="button"
            className="button secondary"
            onClick={() => onFilter({})}
          >
            Сбросить фильтры
          </button>
        )}
      </section>

      {error ? (
        <ErrorNotice error={error} onRetry={() => setAttempt((n) => n + 1)} />
      ) : items === null ? (
        <Loading />
      ) : (
        <>
          <p className="queue-count" role="status">
            Найдено: {items.length}
          </p>
          {items.length === 0 ? (
            <section className="card empty-state">
              <span className="large-icon">
                <Icon name="file" size={34} />
              </span>
              <h2>
                {filtered ? "Заявок с такими условиями нет" : "Очередь пуста"}
              </h2>
              <p>
                {filtered
                  ? "Измените или сбросьте фильтры."
                  : "Отправленные клиентами заявки появятся здесь."}
              </p>
            </section>
          ) : (
            <div
              className="table-scroll card"
              role="region"
              aria-label="Заявки в очереди"
              tabIndex={0}
            >
              <table className="queue-table">
                <thead>
                  <tr>
                    <th scope="col">Компания</th>
                    <th scope="col">Продукт</th>
                    <th scope="col">Статус</th>
                    <th scope="col">Отправлена</th>
                    <th scope="col">Ответственный</th>
                    <th scope="col">Риск</th>
                    <th scope="col" className="num">
                      Запрошено / лимит
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((application) => {
                    const meta = STATUS[application.status];
                    const evaluation = application.latest_evaluation;
                    return (
                      <tr
                        key={application.id}
                        data-application-id={application.id}
                      >
                        <td className="queue-company">
                          <a
                            href={`?application=${encodeURIComponent(application.id)}`}
                            onClick={(event) => open(event, application.id)}
                          >
                            {application.company.name}
                          </a>
                          <small>
                            № {shortId(application.id)} · ИНН{" "}
                            {application.company.inn}
                          </small>
                        </td>
                        <td>{productName(application)}</td>
                        <td>
                          <span className={"status " + meta.tone}>
                            {meta.label}
                          </span>
                        </td>
                        <td>
                          {application.submitted_at
                            ? formatDateTime(application.submitted_at)
                            : "—"}
                        </td>
                        <td className="queue-assignee">
                          {assigneeLabel(application.assignee, userId)}
                        </td>
                        <td className="nowrap">
                          {evaluation?.risk
                            ? `${RISK_SHORT[evaluation.risk]} · ${evaluation.score}`
                            : "Не рассчитан"}
                        </td>
                        <td className="num">
                          <b>
                            {application.requested_amount_rub !== null
                              ? rub(application.requested_amount_rub)
                              : "—"}
                          </b>
                          <small>
                            {evaluation?.scored_limit_rub != null
                              ? `лимит ${rub(evaluation.scored_limit_rub)}`
                              : "лимит не рассчитан"}
                          </small>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      <div className="notice quiet">
        <Icon name="shield" />
        <span>
          В очереди — заявки, отправленные клиентами. Сведения реестра, оборотов
          и БКИ получены по согласию клиента; решения фиксируются в истории
          заявки.
        </span>
      </div>
    </div>
  );
}
