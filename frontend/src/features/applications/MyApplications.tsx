import { MouseEvent, useEffect, useState } from "react";
import {
  ApiError,
  Application,
  applicationsApi,
  errorMessage,
} from "../../api";
import { ErrorNotice, Icon, Loading } from "../../components";
import { formatDate, nextStep, productName, rub, STATUS } from "./format";
import "./applications.css";

/** `?view=applications`: every owned application, newest first, with its status, date and next step. */
export function MyApplications({
  onOpen,
  onRecommend,
  onUnauthorized,
}: {
  onOpen: (id: string) => void;
  onRecommend: () => void;
  onUnauthorized: () => void;
}) {
  const [items, setItems] = useState<Application[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    applicationsApi
      .list(controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setItems(result.items);
      })
      .catch((failure) => {
        if (controller.signal.aborted) return;
        if (failure instanceof ApiError && failure.status === 401)
          onUnauthorized();
        else setError(errorMessage(failure));
      });
    return () => controller.abort();
  }, [attempt]);

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
    <div className="applications-index">
      <div className="page-heading">
        <div className="eyebrow accent">Заявки на финансирование</div>
        <h1>Мои заявки</h1>
        <p>
          Статус каждой заявки и следующий шаг. Черновики сохраняются: анкету
          можно продолжить с того шага, где вы остановились.
        </p>
      </div>
      {error ? (
        <ErrorNotice error={error} onRetry={() => setAttempt((n) => n + 1)} />
      ) : items === null ? (
        <Loading />
      ) : items.length === 0 ? (
        <section className="card empty-state">
          <span className="large-icon">
            <Icon name="file" size={34} />
          </span>
          <h2>Заявок пока нет</h2>
          <p>
            Подберите продукт и начните анкету — черновик сохранится
            автоматически.
          </p>
          <button
            type="button"
            className="button primary"
            onClick={onRecommend}
          >
            Подобрать финансирование
            <Icon />
          </button>
        </section>
      ) : (
        <ul className="application-list">
          {items.map((application) => {
            const meta = STATUS[application.status];
            return (
              <li key={application.id} className="card application-row">
                <div className="row-main">
                  <h2>
                    <a
                      href={`?application=${encodeURIComponent(application.id)}`}
                      onClick={(event) => open(event, application.id)}
                    >
                      {productName(application)}
                      <span className="sr-only">
                        , {application.company.name}, {meta.label}
                      </span>
                    </a>
                  </h2>
                  <p>
                    {application.company.name} · ИНН {application.company.inn}
                  </p>
                </div>
                <div className="row-status">
                  <span className={"status status-pill " + meta.tone}>
                    {meta.label}
                  </span>
                  <p>{nextStep(application)}</p>
                </div>
                <dl className="row-meta">
                  <div>
                    <dt>Запрошено</dt>
                    <dd>
                      {application.requested_amount_rub !== null
                        ? rub(application.requested_amount_rub)
                        : "—"}
                    </dd>
                  </div>
                  <div>
                    <dt>
                      {application.submitted_at ? "Отправлена" : "Создана"}
                    </dt>
                    <dd>
                      {formatDate(
                        application.submitted_at ?? application.created_at,
                      )}
                    </dd>
                  </div>
                </dl>
                <span className="row-open" aria-hidden="true">
                  {application.status === "DRAFT" ? "Продолжить" : "Открыть"}
                  <Icon size={16} />
                </span>
              </li>
            );
          })}
        </ul>
      )}
      <div className="notice quiet">
        <Icon name="shield" />
        <span>
          Уведомления о смене статуса приходят в кабинет. Предварительные оценки
          и одобрения — не окончательное решение банка.
        </span>
      </div>
    </div>
  );
}
