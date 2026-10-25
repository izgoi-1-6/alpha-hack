import { Product } from "../../api";

/**
 * The catalog's own explanation of a product: what it is («Что это»), its features («Особенности») and who it suits
 * («Кому подходит»). Three rows of the card, aligned with the next card of the grid row.
 */
export function ProductExplanation({ product }: { product: Product }) {
  return (
    <div className="product-explanation">
      <section className="product-section">
        <h4>Что это</h4>
        <p className="product-summary">{product.display.summary}</p>
      </section>
      <section className="product-section">
        <h4>Особенности</h4>
        <ul className="product-features">
          {product.display.features.map((feature) => (
            <li key={feature}>{feature}</li>
          ))}
        </ul>
      </section>
      <section className="product-section">
        <h4>Кому подходит</h4>
        <p className="product-best-for">{product.display.best_for}</p>
      </section>
    </div>
  );
}
