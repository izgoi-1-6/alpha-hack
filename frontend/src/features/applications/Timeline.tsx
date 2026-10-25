import { HistoryItem } from "../../api";
import { Icon } from "../../components";
import { formatDateTime, keepAmountsTogether, statusLabel } from "./format";

const ACTOR_LABELS: Record<HistoryItem["actor_role"], string> = {
  client: "Вы",
  officer: "Сотрудник банка",
  system: "Система · автоматическая проверка",
};

/**
 * The application's history in order, each change with the in-app notification it sent. Actors are named from the
 * customer's point of view unless the staff page passes its own `actorLabel`.
 */
export function Timeline<T extends HistoryItem>({
  items,
  actorLabel = (item) => ACTOR_LABELS[item.actor_role],
}: {
  items: T[];
  actorLabel?: (item: T) => string;
}) {
  return (
    <section className="card timeline-card" aria-labelledby="history-heading">
      <div className="panel-title">
        <h2 id="history-heading">История заявки</h2>
      </div>
      <ol className="timeline" aria-labelledby="history-heading">
        {items.map((item, index) => (
          <li
            key={item.id}
            className={index === items.length - 1 ? "current" : undefined}
          >
            <span className="timeline-marker" aria-hidden="true" />
            <div className="timeline-body">
              <div className="timeline-head">
                <strong>{statusLabel(item.to_status)}</strong>
                <time dateTime={item.created_at}>
                  {formatDateTime(item.created_at)}
                </time>
              </div>
              <p>{keepAmountsTogether(item.reason_text)}</p>
              <small>{actorLabel(item)}</small>
              {item.notification && (
                <div className="timeline-notification">
                  <span>
                    <Icon name="info" size={15} />
                    Уведомление в кабинете
                  </span>
                  <p>{keepAmountsTogether(item.notification.message)}</p>
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
