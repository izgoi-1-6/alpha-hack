import { Product, Recommendation } from "../../api";
import { Icon } from "../../components";
import { CommandProblem } from "../applications/commands";

export const money = (n: number | null) =>
  n === null
    ? "Нужно уточнить"
    : new Intl.NumberFormat("ru-RU").format(n) + " ₽";
const labels = {
  fits: "Соответствует потребности",
  needs_info: "Нужны сведения",
  does_not_fit: "Не соответствует параметрам",
};

/** Starting a questionnaire from this card: only offered where the server says `can_apply`. */
export type CardStart = {
  pending: boolean;
  busy: boolean;
  problem: CommandProblem | null;
  onStart: () => void;
  onRefresh: () => void;
};

export function ProductCard({
  item,
  product,
  guided,
  onRecalculate,
  start,
}: {
  item: Recommendation;
  product: Product;
  guided: boolean;
  onRecalculate: (amount: number) => void;
  start: CardStart;
}) {
  return (
    <article
      className={"card product-card " + (guided ? item.status : "")}
      data-product-id={item.product_id}
      aria-labelledby={"product-title-" + item.product_id}
    >
      {guided && (
        <div className="product-top">
          <span
            className={
              "status " +
              (item.status === "fits"
                ? "success"
                : item.status === "needs_info"
                  ? "warning"
                  : "neutral")
            }
          >
            {labels[item.status]}
          </span>
          <span className="product-rank">
            <span aria-hidden="true">{String(item.rank).padStart(2, "0")}</span>
            <span className="sr-only">Место {item.rank}</span>
          </span>
        </div>
      )}
      <h3 id={"product-title-" + item.product_id}>{product.name}</h3>
      <p className="product-subtitle">
        {product.collateral_required
          ? `С залогом · оценка до ${(product.collateral_ltv_bps ?? 0) / 100}% его заявленной стоимости`
          : "Без залога"}{" "}
        · {product.term_min_months}–{product.term_max_months} мес.
      </p>
      <div className="product-metrics">
        <div>
          <span>Личная предварительная оценка</span>
          <strong>{money(item.indicative_limit_rub)}</strong>
          <small>Максимум продукта {money(item.catalog_max_rub)}</small>
        </div>
        <div>
          <span>
            {product.instrument_type === "revolving_credit_line"
              ? "Проценты в месяц"
              : "Платёж в месяц"}
          </span>
          <strong>{money(item.estimated_payment_rub)}</strong>
          <small>
            Учебная ставка{" "}
            {(product.annual_rate_bps / 100).toLocaleString("ru-RU")}% годовых
          </small>
        </div>
      </div>
      <p className="payment-note">{item.payment_note}</p>
      {guided && (
        <div className="fit-reasons">
          {item.reasons.map((reason) => (
            <p key={reason}>{reason}</p>
          ))}
        </div>
      )}
      <div
        className={
          "application-eligibility " + (item.can_apply ? "available" : "")
        }
      >
        <Icon name={item.can_apply ? "check" : "info"} size={16} />
        <span>
          {item.can_apply
            ? "Можно начать анкету: итоговая сумма и решение определяются после рассмотрения."
            : "Для начала анкеты измените несовместимые параметры или уточните статус компании."}
        </span>
      </div>
      {item.can_apply && (
        <div className="application-start">
          <button
            className="button primary"
            onClick={start.onStart}
            disabled={start.busy}
          >
            {start.pending ? "Создаём черновик…" : "Начать анкету"}
            <Icon />
          </button>
          {start.problem && (
            <div className="notice error" role="alert">
              <Icon name="info" />
              <div>
                {start.problem.message}
                {start.problem.kind === "stale" && (
                  <button
                    className="button secondary"
                    onClick={start.onRefresh}
                  >
                    <Icon name="refresh" size={17} />
                    Пересчитать оценку
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}
      {guided && item.alternatives.length > 0 && (
        <div className="product-alternatives">
          {item.alternatives.map((text) => (
            <p key={text}>{text}</p>
          ))}
          {item.indicative_limit_rub !== null &&
            item.indicative_limit_rub >= product.amount_min_rub &&
            item.requested_amount_rub > item.indicative_limit_rub && (
              <button
                className="button secondary"
                onClick={() => onRecalculate(item.indicative_limit_rub!)}
              >
                Рассчитать на {money(item.indicative_limit_rub)}
              </button>
            )}
        </div>
      )}
      {guided && (
        <details className="criteria">
          <summary>
            Все критерии соответствия{" "}
            <span>
              {item.checks.filter((c) => c.result === "passed").length} из{" "}
              {item.checks.length}
            </span>
          </summary>
          <ul>
            {item.checks.map((check) => (
              <li key={check.code}>
                <span
                  className={"criterion-mark " + check.result}
                  aria-hidden="true"
                >
                  {check.result === "passed"
                    ? "✓"
                    : check.result === "failed"
                      ? "×"
                      : "?"}
                </span>
                <span className="sr-only">
                  {check.result === "passed"
                    ? "Выполнено: "
                    : check.result === "failed"
                      ? "Не выполнено: "
                      : "Нужно уточнить: "}
                </span>
                {check.text}
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}
