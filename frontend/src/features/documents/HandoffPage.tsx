import { useEffect, useState } from "react";
import { ApiError, Application, applicationsApi, errorMessage } from "../../api";
import { DemoBadge, ErrorNotice, Icon, Loading } from "../../components";
import { Amount } from "../applications/Amount";
import { productName, rub, statusLabel } from "../applications/format";
import { shortId } from "../officer/officerFormat";
import "../applications/applications.css";
import "./documents.css";

type State =
  | { kind: "loading" }
  | { kind: "failed"; notFound: boolean; message: string }
  | { kind: "loaded"; application: Application };

/**
 * `/alfa-business/{id}`: the local page the approved customer reaches through «Перейти в Альфа-Бизнес (демо)»,
 * also by a direct link. It reads the application as its owner (another client gets the server's 404) and confirms a
 * simulation only for an APPROVED one: no bank redirect, signing or disbursement, and APPROVED is not money issued.
 */
export function HandoffPage({
  applicationId,
  onOpenApplication,
  onOpenList,
  onUnauthorized,
}: {
  applicationId: string;
  onOpenApplication: (id: string) => void;
  onOpenList: () => void;
  onUnauthorized: () => void;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    applicationsApi
      .get(applicationId, controller.signal)
      .then(({ application }) => setState({ kind: "loaded", application }))
      .catch((error) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 401) return onUnauthorized();
        setState({
          kind: "failed",
          notFound: error instanceof ApiError && error.status === 404,
          message: errorMessage(error),
        });
      });
    return () => controller.abort();
  }, [applicationId, attempt]);

  if (state.kind === "loading") return <Loading />;
  if (state.kind === "failed")
    return state.notFound ? (
      <div className="handoff-page">
        <div className="page-heading">
          <div className="eyebrow accent">Альфа-Бизнес · демо</div>
          <h1>Страница недоступна</h1>
          <p>Заявка не найдена или принадлежит другому клиенту.</p>
        </div>
        <button type="button" className="button primary" onClick={onOpenList}>
          Перейти к моим заявкам
          <Icon />
        </button>
      </div>
    ) : (
      <ErrorNotice error={state.message} onRetry={() => setAttempt((n) => n + 1)} />
    );

  const application = state.application;
  if (application.status !== "APPROVED")
    return (
      <div className="handoff-page">
        <div className="page-heading">
          <div className="eyebrow accent">Альфа-Бизнес · демо</div>
          <h1>Переход пока недоступен</h1>
          <p>
            Демонстрационная страница открывается только после окончательного
            одобрения заявки. Сейчас статус заявки — «{statusLabel(application.status)}».
          </p>
        </div>
        <button
          type="button"
          className="button primary"
          onClick={() => onOpenApplication(application.id)}
        >
          Открыть заявку
          <Icon />
        </button>
      </div>
    );

  return (
    <div className="handoff-page">
      <div className="page-heading handoff-heading">
        <div>
          <div className="eyebrow accent">Демонстрационный переход · заявка № {shortId(application.id)}</div>
          <h1>Альфа-Бизнес (демо)</h1>
          <p>
            {application.company.name} · ИНН {application.company.inn} · {productName(application)}
          </p>
        </div>
        <DemoBadge />
      </div>
      <section className="card handoff-card" aria-labelledby="handoff-heading">
        <h2 id="handoff-heading">Это имитация перехода в интернет-банк</h2>
        <p>
          Настоящего Альфа-Бизнеса здесь нет: страница — часть демо-стенда
          «Кредитный маршрут». Одобрение заявки — демонстрационное решение, а не
          выданный кредит.
        </p>
        <ul className="handoff-facts">
          <li>
            <Icon name="shield" size={18} />
            Деньги не перечисляются: счёт и платежи не открываются.
          </li>
          <li>
            <Icon name="shield" size={18} />
            Кредитный договор не подписывается — ни электронной подписью, ни иначе.
          </li>
          <li>
            <Icon name="shield" size={18} />
            Сведения никуда не передаются: стенд не обращается к банку.
          </li>
        </ul>
      </section>
      <div className="amounts">
        <Amount
          label="Итоговая сумма (демо-решение)"
          tone="approved"
          value={application.final_amount_rub !== null ? rub(application.final_amount_rub) : "Не указана"}
          note="Демонстрационное решение: деньги не перечисляются."
        />
      </div>
      <div className="status-actions">
        <button
          type="button"
          className="button primary"
          onClick={() => onOpenApplication(application.id)}
        >
          Вернуться к заявке
        </button>
        <button type="button" className="button secondary" onClick={onOpenList}>
          Мои заявки
        </button>
      </div>
    </div>
  );
}
