import { ConditionToConfirm, Product, Recommendation } from "../../api";
import { keepAmountsTogether } from "../applications/format";

const MARKS = {
  passed: { mark: "✓", spoken: "Выполнено: " },
  failed: { mark: "×", spoken: "Не выполнено: " },
  unknown: { mark: "?", spoken: "Нужно уточнить: " },
};
const KINDS: [ConditionToConfirm["kind"], string][] = [
  ["requirement", "Требования к заёмщику"],
  ["category", "Приоритетные категории"],
  ["okved", "Ограничения по деятельности"],
];

/**
 * «Условия программы»: what was checked automatically against the company's data, what the bank confirms during the
 * review (the catalog's conditions to confirm — informational, never blocking), the term's own note and the
 * remaining notes of the calculation.
 */
export function ProductConditions({
  item,
  product,
}: {
  item: Recommendation;
  product: Product;
}) {
  const passed = item.checks.filter((check) => check.result === "passed");
  const checked = new Set(item.checks.map((check) => check.text));
  const notes = item.reasons.filter((reason) => !checked.has(reason));
  return (
    <details className="product-conditions">
      <summary>
        Условия программы{" "}
        <span>
          проверено {passed.length} из {item.checks.length}
        </span>
      </summary>
      <div className="conditions-body">
        <p className="conditions-title">Проверено по данным компании</p>
        <ul className="criteria-list">
          {item.checks.map((check) => (
            <li key={check.code}>
              <span
                className={"criterion-mark " + check.result}
                aria-hidden="true"
              >
                {MARKS[check.result].mark}
              </span>
              <span>
                <span className="sr-only">{MARKS[check.result].spoken}</span>
                {keepAmountsTogether(check.text)}
              </span>
            </li>
          ))}
        </ul>
        {KINDS.map(([kind, title]) => {
          const entries = item.conditions_to_confirm.filter(
            (condition) => condition.kind === kind,
          );
          return entries.length ? (
            <div key={kind}>
              <p className="conditions-title">
                {title} · подтвердит банк при рассмотрении
              </p>
              <ul className="conditions-list">
                {entries.map((condition) => (
                  <li key={condition.text}>{condition.text}</li>
                ))}
              </ul>
            </div>
          ) : null;
        })}
        {product.term_note && (
          <p className="conditions-note">
            <b>Срок.</b> {product.term_note}
          </p>
        )}
        {notes.map((note) => (
          <p key={note} className="conditions-note">
            {keepAmountsTogether(note)}
          </p>
        ))}
      </div>
    </details>
  );
}
