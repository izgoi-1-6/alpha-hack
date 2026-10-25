import { useId } from "react";
import { Product, Recommendation } from "../../api";
import { rub } from "../applications/format";
import { COLLATERAL, paymentTitle, rateText, termText } from "./productText";

/**
 * The card's figures: the personal estimate beside the product maximum (two different amounts, never one for the
 * other), the indicative payment with its preferential label, and the rate, term and collateral terms.
 */
export function ProductFigures({
  item,
  product,
  inactive,
}: {
  item: Recommendation;
  product: Product;
  /** The company does not operate: no personal estimate is shown. */
  inactive: boolean;
}) {
  const estimate = useId();
  const payment = useId();
  const rate = rateText(product);
  return (
    <div className="product-figures">
      <div className="product-figure-pair">
        <div
          className="product-figure product-estimate"
          role="group"
          aria-labelledby={estimate}
        >
          <span id={estimate}>Личная предварительная оценка</span>
          <strong>
            {inactive
              ? "Не рассчитывается"
              : item.indicative_limit_rub === null
                ? "Нужно уточнить"
                : rub(item.indicative_limit_rub)}
          </strong>
          <small>Максимум продукта {rub(item.catalog_max_rub)}</small>
        </div>
        <div
          className="product-figure product-payment"
          role="group"
          aria-labelledby={payment}
        >
          <span id={payment}>{paymentTitle(product)}</span>
          <strong>
            {item.estimated_payment_rub === null
              ? "Не рассчитан"
              : rub(item.estimated_payment_rub)}
          </strong>
          {item.payment_label && <small>{item.payment_label}</small>}
        </div>
      </div>
      <dl className="product-terms">
        <div>
          <dt>Ставка</dt>
          <dd>
            {rate.value}
            {rate.period && <small>{rate.period}</small>}
          </dd>
        </div>
        <div>
          <dt>Срок</dt>
          <dd>{termText(product)}</dd>
        </div>
        <div>
          <dt>Залог</dt>
          <dd>{COLLATERAL[product.collateral_mode]}</dd>
        </div>
      </dl>
    </div>
  );
}
