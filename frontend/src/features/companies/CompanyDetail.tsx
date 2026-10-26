import { CompanyResult } from "../../api";
import { Icon, ErrorNotice } from "../../components";
const formatMoney = (value: number | null) =>
  value === null
    ? "Нет данных"
    : new Intl.NumberFormat("ru-RU").format(value) + " ₽";
const formatDate = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat("ru-RU", {
        day: "numeric",
        month: "long",
        year: "numeric",
      }).format(new Date(value))
    : "Нет данных";
export function CompanyDetail({
  data,
  busy,
  error,
  onRetry,
  onRecommend,
}: {
  data: CompanyResult;
  busy: boolean;
  error: string;
  onRetry: () => void;
  onRecommend: () => void;
}) {
  const { company: c, precheck: p } = data;
  const active = c.registry_status === "active",
    unknown = c.registry_status === "unknown";
  return (
    <>
      <div className="page-heading detail-heading">
        <div>
          <div className="eyebrow accent">Профиль компании</div>
          <h1>{c.name ?? "Ваша компания"}</h1>
          <p>Сведения о бизнесе и результаты предварительной проверки.</p>
        </div>
        <span
          className={
            "status " + (active ? "success" : unknown ? "warning" : "neutral")
          }
        >
          {active
            ? "Действующая компания"
            : unknown
              ? "Статус уточняется"
              : "Деятельность прекращена"}
        </span>
      </div>
      {!active && (
        <div className={"notice " + (unknown ? "caution" : "quiet")}>
          <Icon name="info" />
          <div>
            <strong>
              {unknown
                ? "Реестр временно недоступен"
                : "Компания доступна только для просмотра"}
            </strong>
            <p>
              {unknown
                ? "Не можем подтвердить статус компании. Повторите проверку, чтобы получить актуальные сведения."
                : "Заявку можно отправить только для действующей компании. Сведения сохранены для ознакомления."}
            </p>
          </div>
        </div>
      )}
      <div className="recommendation-entry card" data-tour="find-financing">
        <div>
          <h2>От задачи — к подходящему продукту</h2>
          <p>
            Выберите сумму — сравним продукты каталога и оценим платёж по
            обороту компании.
          </p>
        </div>
        <button className="button primary" onClick={onRecommend}>
          Подобрать финансирование <Icon />
        </button>
      </div>
      <div className="summary-grid">
        <section className="card finance-card">
          <span className="card-label">Среднемесячный оборот</span>
          <div className="money">{formatMoney(p.monthly_revenue_rub)}</div>
          <p>
            {p.monthly_revenue_rub === null
              ? "Источник не предоставил обороты. Можно повторить запрос."
              : "По синтетическим данным за последний финансовый период"}
          </p>
          <div className="finance-bottom">
            <span>Конец финансового периода</span>
            <b>{formatDate(p.financial_period_end)}</b>
          </div>
        </section>
        <section className="card registry-card">
          <div className="card-label">
            Сведения о компании <Icon name="building" />
          </div>
          <dl>
            <div>
              <dt>ИНН</dt>
              <dd className="mono">{c.inn}</dd>
            </div>
            <div>
              <dt>Форма бизнеса</dt>
              <dd>
                {c.entity_type === "IP"
                  ? "Индивидуальный предприниматель"
                  : "ООО"}
              </dd>
            </div>
            <div>
              <dt>Дата регистрации</dt>
              <dd>{formatDate(c.registered_at)}</dd>
            </div>
            <div>
              <dt>Основной ОКВЭД</dt>
              <dd>{c.okved ?? "Нет данных"}</dd>
            </div>
            <div>
              <dt>Регион</dt>
              <dd>{c.region ?? "Нет данных"}</dd>
            </div>
          </dl>
        </section>
      </div>
      <section className="card precheck-card">
        <div className="section-header">
          <div>
            <div className="eyebrow">Прозрачная проверка</div>
            <h2>Что удалось узнать</h2>
          </div>
        </div>
        <div className="source-row">
          <span className="source-icon">
            <Icon name="building" />
          </span>
          <div>
            <b>Реестр компаний</b>
            <p>
              {p.registry_source_status === "available"
                ? "Сведения о регистрации и статусе компании получены."
                : "Источник временно недоступен. Можно повторить запрос."}
            </p>
          </div>
          <span
            className={
              "status " +
              (p.registry_source_status === "available" ? "success" : "warning")
            }
          >
            {p.registry_source_status === "available"
              ? "Получено"
              : "Недоступен"}
          </span>
        </div>
        <div className="source-row">
          <span className="source-icon">
            <Icon name="route" />
          </span>
          <div>
            <b>Обороты бизнеса</b>
            <p>
              {p.turnover_source_status === "available"
                ? "Сведения о выручке получены для дальнейшей оценки."
                : "Источник не предоставил данные. Финансовая оценка пока недоступна."}
            </p>
          </div>
          <span
            className={
              "status " +
              (p.turnover_source_status === "available" ? "success" : "warning")
            }
          >
            {p.turnover_source_status === "available"
              ? "Получено"
              : "Нет данных"}
          </span>
        </div>
        <div className="source-row">
          <span className="source-icon">
            <Icon name="shield" />
          </span>
          <div>
            <b>Кредитная история</b>
            <p>
              Запрос возможен только после отдельного согласия при отправке
              заявки.
            </p>
          </div>
          <span className="status neutral">Не запрашивалась</span>
        </div>
        {error && <ErrorNotice error={error} />}
        <div className="precheck-footer">
          <span>
            <Icon name="clock" size={16} />
            Проверено{" "}
            {new Intl.DateTimeFormat("ru-RU", {
              day: "numeric",
              month: "short",
              hour: "2-digit",
              minute: "2-digit",
            }).format(new Date(p.checked_at))}
          </span>
          <button
            className="button secondary"
            onClick={onRetry}
            disabled={busy}
          >
            <Icon name="refresh" size={17} />
            {busy ? "Обновляем…" : "Повторить проверку"}
          </button>
        </div>
      </section>
      <div className="notice quiet">
        <Icon name="info" />
        <span>
          Это предварительная проверка синтетических источников. Она не является
          предодобрением или обещанием выдачи кредита.
        </span>
      </div>
    </>
  );
}
