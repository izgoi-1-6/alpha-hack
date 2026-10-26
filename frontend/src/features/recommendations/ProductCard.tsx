import { Product, Recommendation } from "../../api";
import { Icon } from "../../components";
import { CommandProblem } from "../applications/commands";
import { keepAmountsTogether, rub } from "../applications/format";
import { ProductConditions } from "./ProductConditions";
import { ProductExplanation } from "./ProductExplanation";
import { ProductFigures } from "./ProductFigures";
import { STATUS } from "./productText";

/** Starting a questionnaire from this card: only offered where the server says `can_apply`. */
export type CardStart = {
  pending: boolean;
  busy: boolean;
  problem: CommandProblem | null;
  onStart: () => void;
  onRefresh: () => void;
};

/**
 * One catalog product for the chosen amount, in the grid's fixed rows (header, the three explanations, figures,
 * payment note, badges, fit, conditions, action) so that both cards of a grid row line up section by section.
 */
export function ProductCard({
  item,
  product,
  onRecalculate,
  start,
}: {
  item: Recommendation;
  product: Product;
  onRecalculate: (amount: number) => void;
  start: CardStart;
}) {
  const status = STATUS[item.status];
  const best = item.rank === 1 && item.status === "fits";
  const inactive = item.checks.some(
    (check) => check.code === "company_active" && check.result === "failed",
  );
  // A company that does not operate has no personal estimate («Не рассчитывается»): no line about it either.
  const issues = item.checks.filter(
    (check) =>
      check.result !== "passed" &&
      !(inactive && check.code === "amount_capacity"),
  );
  const limit = item.indicative_limit_rub;
  // The amount is the one thing this screen changes: offer the product's bound when only the amount is outside it,
  // or the personal estimate when the request is above it — never for a company that does not operate.
  const failed = issues.filter((check) => check.result === "failed");
  const onlyAmount =
    failed.length > 0 &&
    failed.every((check) => ["amount_min", "catalog_max"].includes(check.code));
  const target = inactive
    ? null
    : onlyAmount
    ? failed[0].code === "amount_min"
      ? product.amount_min_rub
      : product.amount_max_rub
    : limit !== null &&
        limit >= product.amount_min_rub &&
        item.requested_amount_rub > limit
      ? limit
      : null;
  return (
    <article
      className={"card product-card " + item.status + (best ? " best" : "")}
      data-product-id={item.product_id}
      aria-labelledby={"product-title-" + item.product_id}
    >
      <header className="product-head" data-tour="product-head">
        <div className="product-top">
          <span className={"status product-status " + status.tone}>
            {status.label}
          </span>
          {best && <span className="product-tag best">Лучшее совпадение</span>}
          {product.kind === "gov_program" && (
            <span className="product-tag">Госпрограмма</span>
          )}
          <span className="product-rank">
            <span aria-hidden="true">{String(item.rank).padStart(2, "0")}</span>
            <span className="sr-only">Место {item.rank}</span>
          </span>
        </div>
        <h3 id={"product-title-" + item.product_id}>{product.name}</h3>
        {product.display.headline && (
          <p className="product-headline">{product.display.headline}</p>
        )}
      </header>
      <ProductExplanation product={product} />
      <ProductFigures item={item} product={product} inactive={inactive} />
      <p className="product-note">{keepAmountsTogether(item.payment_note)}</p>
      <div className="product-badges">
        {item.badges.map((badge) => (
          <p key={badge.overlay_id} className="product-badge">
            <Icon name="shield" size={18} />
            <span>
              <b>{badge.name}.</b> {badge.text}
            </span>
          </p>
        ))}
      </div>
      <div className="product-fit">
        {item.status !== "fits" && (
          <div className="product-fit-box">
            <ul>
              {issues.map((check) => (
                <li key={check.code} className={check.result}>
                  <span className="sr-only">
                    {check.result === "failed"
                      ? "Не выполнено: "
                      : "Нужно уточнить: "}
                  </span>
                  {keepAmountsTogether(check.text)}
                </li>
              ))}
            </ul>
            {item.alternatives.map((text) => (
              <p key={text}>{keepAmountsTogether(text)}</p>
            ))}
            {target !== null && (
              <button
                className="button secondary"
                onClick={() => onRecalculate(target)}
              >
                Рассчитать на {rub(target)}
              </button>
            )}
          </div>
        )}
      </div>
      <ProductConditions item={item} product={product} />
      <div className="product-action">
        <p
          className={
            "application-eligibility " + (item.can_apply ? "available" : "")
          }
        >
          <Icon name={item.can_apply ? "check" : "info"} size={16} />
          <span>
            {item.can_apply
              ? "Можно начать анкету: итоговая сумма и решение определяются после рассмотрения."
              : inactive
                ? "Анкету можно начать только для действующей компании."
                : "Для начала анкеты измените несовместимые параметры или уточните статус компании."}
          </span>
        </p>
        {item.can_apply && (
          <div className="application-start">
            <button
              className="button primary product-start"
              data-tour="start-application"
              onClick={start.onStart}
              disabled={start.busy}
              aria-describedby={"product-title-" + item.product_id}
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
      </div>
    </article>
  );
}
