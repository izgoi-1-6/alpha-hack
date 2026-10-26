import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  ApiError,
  Catalog,
  CompanyResult,
  Need,
  RecommendationSnapshot,
  recommendationsApi,
  errorMessage,
} from "../../api";
import { ErrorNotice, Icon, Loading } from "../../components";
import { CommandAttempts } from "../applications/commands";
import { rub } from "../applications/format";
import { useStartApplication } from "../applications/useStartApplication";
import { AmountSlider } from "./AmountSlider";
import { ProductCard } from "./ProductCard";
import { products } from "./productText";
import "./recommendations.css";

/**
 * The product choice: the amount is the only input (purpose, term and collateral are chosen in the questionnaire),
 * every catalog product is a card in the server's ranking order. Each amount change saves a new snapshot after a
 * short pause; an older response never describes a newer amount.
 */
export function Recommendations({
  data,
  onBack,
  attempts,
  onApplicationCreated,
  onUnauthorized,
}: {
  data: CompanyResult;
  onBack: () => void;
  attempts: CommandAttempts;
  onApplicationCreated: (applicationId: string) => void;
  onUnauthorized: () => void;
}) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [catalogAttempt, setCatalogAttempt] = useState(0);
  // Null until the catalog gives the slider's default amount; `valid` is false while the typed amount is unusable.
  const [need, setNeed] = useState<Need | null>(null);
  const [valid, setValid] = useState(true);
  const [snapshot, setSnapshot] = useState<RecommendationSnapshot | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const requestRevision = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const amountSlider = useRef<HTMLInputElement>(null);
  // While a new amount is calculated the grid keeps its last height, so the page does not collapse and jump.
  const grid = useRef<HTMLDivElement>(null);
  const gridHeight = useRef(0);
  useLayoutEffect(() => {
    if (snapshot && grid.current)
      gridHeight.current = grid.current.offsetHeight;
  }, [snapshot]);
  const unauthorized = (e: unknown) =>
    e instanceof ApiError && e.status === 401;

  useEffect(() => {
    const read = new AbortController();
    setCatalogError("");
    recommendationsApi
      .catalog(read.signal)
      .then((result) => {
        setCatalog(result);
        setNeed(
          (current) =>
            current ?? {
              requested_amount_rub: result.amount_slider.default_rub,
            },
        );
      })
      .catch((e) => {
        if (read.signal.aborted) return;
        if (unauthorized(e)) onUnauthorized();
        else setCatalogError(errorMessage(e));
      });
    return () => read.abort();
  }, [catalogAttempt]);

  /**
   * A new amount (null: the typed text is unusable). Invalidates at once, before React runs effect cleanup. The
   * amount already shown (Home at the minimum, End at the maximum, the pressed preset) is not calculated again,
   * unless `force` asks for a fresh snapshot of it or the last calculation failed.
   */
  function update(amount: number | null, force = false) {
    if (
      !force &&
      amount !== null &&
      valid &&
      !error &&
      amount === need?.requested_amount_rub
    )
      return;
    requestRevision.current += 1;
    controller.current?.abort();
    setSnapshot(null);
    setError("");
    setValid(amount !== null);
    if (amount !== null) setNeed({ requested_amount_rub: amount });
    setPending(amount !== null);
  }
  useEffect(() => {
    if (!need) return;
    const revision = ++requestRevision.current;
    const read = new AbortController();
    controller.current = read;
    const active = () =>
      !read.signal.aborted && revision === requestRevision.current;
    setPending(valid);
    setError("");
    const timer = window.setTimeout(async () => {
      if (!valid) return;
      try {
        const result = await recommendationsApi.calculate(
          data.company.id,
          need,
          read.signal,
        );
        if (active()) setSnapshot(result);
      } catch (e) {
        if (!active()) return;
        if (unauthorized(e)) onUnauthorized();
        else setError(errorMessage(e));
      } finally {
        if (active()) setPending(false);
      }
    }, 300);
    return () => {
      window.clearTimeout(timer);
      read.abort();
      requestRevision.current += 1;
    };
  }, [need, valid, data.company.id, refresh]);

  const start = useStartApplication({
    companyId: data.company.id,
    snapshotId: snapshot?.snapshot_id ?? null,
    attempts,
    onCreated: onApplicationCreated,
    onUnauthorized,
  });
  const registry = data.company.registry_status;
  const revenue = data.precheck.monthly_revenue_rub;
  const items = snapshot?.items ?? [];
  const fitting = items.filter((item) => item.status === "fits").length;
  const summary = !valid
    ? "Укажите сумму в пределах шкалы, чтобы увидеть продукты."
    : error
      ? `Не удалось рассчитать продукты для суммы ${need ? rub(need.requested_amount_rub) : ""}.`
      : pending || !snapshot
      ? `Пересчитываем для суммы ${need ? rub(need.requested_amount_rub) : ""}…`
      : `${products(items.length)} для суммы ${rub(items[0]?.requested_amount_rub ?? need!.requested_amount_rub)} · подходят ${fitting} · сначала подходящие по сумме и условиям`;

  return (
    <>
      <button className="back-link" onClick={onBack}>
        ← Профиль компании
      </button>
      <div className="page-heading">
        <div className="eyebrow accent">Подбор финансирования</div>
        <h1>Найдём подходящий маршрут</h1>
        <p>
          {data.company.name} · ИНН {data.company.inn}
        </p>
      </div>
      <div className="notice quiet">
        <Icon name="shield" />
        <span>
          Предварительная оценка по обороту, не предодобрение. БКИ не
          запрашивается. Ставки и условия взяты из каталога продуктов.
        </span>
      </div>
      {registry !== "active" && (
        <div
          className={"notice " + (registry === "unknown" ? "caution" : "quiet")}
        >
          <Icon name="info" />
          <span>
            {registry === "unknown"
              ? "Статус компании в реестре не подтверждён: заявка пока недоступна, а оценки даны для ориентира. Повторите проверку в профиле компании."
              : "Компания не действует: подбор доступен только для ознакомления, заявку отправить нельзя."}
          </span>
        </div>
      )}
      {!(revenue !== null && revenue > 0) && (
        <div className="notice caution">
          <Icon name="info" />
          <span>
            Нет положительных сведений об обороте: личный лимит и платёж не
            рассчитываются. Эти сведения можно дополнить в анкете.
          </span>
        </div>
      )}
      {catalogError ? (
        <ErrorNotice
          error={catalogError}
          onRetry={() => setCatalogAttempt((n) => n + 1)}
        />
      ) : !catalog || !need ? (
        <Loading />
      ) : (
        <>
          <AmountSlider
            config={catalog.amount_slider}
            amount={need.requested_amount_rub}
            onChange={(amount) => update(amount)}
            sliderRef={amountSlider}
          >
            <div className="amount-turnover">
              <span>Среднемесячный оборот</span>
              <strong>{revenue === null ? "Нет данных" : rub(revenue)}</strong>
              <small>
                Личная оценка ограничена оборотом, даже при наличии залога.
              </small>
            </div>
          </AmountSlider>
          <section
            className="recommendation-results"
            aria-labelledby="results-heading"
            aria-busy={pending && valid}
          >
            <div className="results-heading">
              <div className="eyebrow">Сравнение</div>
              <h2 id="results-heading">Продукты для вашего бизнеса</h2>
              <p className="results-summary" role="status">
                {summary}
              </p>
            </div>
            {error && (
              <ErrorNotice
                error={error}
                onRetry={() => setRefresh((x) => x + 1)}
              />
            )}
            <div
              id="product-grid"
              ref={grid}
              className="product-grid"
              style={
                pending && valid && !snapshot
                  ? { minHeight: gridHeight.current }
                  : undefined
              }
            >
              {items.map((item) => {
                const product = catalog.products.find(
                  (p) => p.id === item.product_id,
                );
                if (!product) return null;
                return (
                  <ProductCard
                    key={item.product_id}
                    item={item}
                    product={product}
                    onRecalculate={(amount) => {
                      // The card is replaced by the new results: focus goes to the slider of the amount that changed.
                      update(amount);
                      amountSlider.current?.focus();
                    }}
                    start={{
                      pending: start.pending === item.product_id,
                      busy: start.pending !== null,
                      problem:
                        start.problem?.productId === item.product_id
                          ? start.problem.problem
                          : null,
                      onStart: () => void start.start(item.product_id),
                      // A fresh calculation saves a new snapshot under the current catalog and rules.
                      onRefresh: () => update(need.requested_amount_rub, true),
                    }}
                  />
                );
              })}
            </div>
            {snapshot && (
              <p className="snapshot-note">
                Оценка сохранена ·{" "}
                {new Date(snapshot.created_at).toLocaleTimeString("ru-RU", {
                  hour: "2-digit",
                  minute: "2-digit",
                })}{" "}
                · {snapshot.rules_version}
                <br />
                Снимок {snapshot.snapshot_id}
              </p>
            )}
          </section>
        </>
      )}
    </>
  );
}
