import { HistoryItem } from "../../api";
import { DemoBadge } from "../../components";
import { formatDateTime, keepAmountsTogether, statusLabel } from "./format";

/** The application's history in order; each simulated in-app notification is labelled as an imitation. */
export function Timeline({
  items,
  userId,
}: {
  items: HistoryItem[];
  userId: string;
}) {
  const actor = (item: HistoryItem) =>
    item.actor_id === null
      ? "Система · демо-проверка"
      : item.actor_id === userId
        ? "Вы"
        : "Сотрудник банка";
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
              <small>{actor(item)}</small>
              {item.notification && (
                <div className="timeline-notification">
                  <DemoBadge label="Демо · имитация уведомления" />
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
