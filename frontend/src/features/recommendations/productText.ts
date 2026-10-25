import { Product, Recommendation } from "../../api";

/** The card's fit status in words; every tone is paired with its text. */
export const STATUS: Record<
  Recommendation["status"],
  { label: string; tone: "success" | "warning" | "neutral" }
> = {
  fits: { label: "Соответствует потребности", tone: "success" },
  needs_info: { label: "Нужны сведения", tone: "warning" },
  does_not_fit: { label: "Не соответствует параметрам", tone: "neutral" },
};

const percent = (bps: number) => (bps / 100).toLocaleString("ru-RU");

/**
 * «23,5% годовых»; a preferential rate adds its period («льготная, первые 12 мес.»); «Ставка уточняется» when the
 * bank does not publish the rate.
 */
export function rateText(product: Product): {
  value: string;
  period: string | null;
} {
  if (product.annual_rate_bps === null)
    return { value: "Ставка уточняется", period: null };
  return {
    value: `${percent(product.annual_rate_bps)}% годовых`,
    period:
      product.rate_certainty === "preferential" &&
      product.rate_preferential_months
        ? `льготная, первые ${product.rate_preferential_months} мес.`
        : null,
  };
}

/** «12–60 мес.», or «бессрочно» for a product without a term. */
export const termText = (product: Product) =>
  product.term_min_months !== null && product.term_max_months !== null
    ? `${product.term_min_months}–${product.term_max_months} мес.`
    : "бессрочно";

export const COLLATERAL: Record<Product["collateral_mode"], string> = {
  none: "Не нужен",
  optional: "По желанию",
  required: "Нужен",
};

export const paymentTitle = (product: Product) =>
  product.payment_model === "interest_full_utilization"
    ? "Проценты в месяц"
    : "Платёж в месяц";

/** «1 продукт», «3 продукта», «11 продуктов». */
export function products(count: number) {
  const tail = count % 100;
  const last = count % 10;
  const word =
    tail >= 11 && tail <= 14
      ? "продуктов"
      : last === 1
        ? "продукт"
        : last >= 2 && last <= 4
          ? "продукта"
          : "продуктов";
  return `${count} ${word}`;
}
