import { useEffect, useRef, useState } from "react";
import {
  Catalog,
  CompanyResult,
  Need,
  RecommendationSnapshot,
  recommendationsApi,
  errorMessage,
} from "../../api";
import { DemoBadge, ErrorNotice, Icon } from "../../components";
import { CommandAttempts } from "../applications/commands";
import { useStartApplication } from "../applications/useStartApplication";
import { ProductCard, money } from "./ProductCard";

// The need is the amount alone: purpose, term and collateral are chosen in the questionnaire.
const initial: Need = { requested_amount_rub: 1500000 };
const MAX_AMOUNT = 2000000000;

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
  const [need, setNeed] = useState<Need>(initial);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [snapshot, setSnapshot] = useState<RecommendationSnapshot | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(true);
  const [refresh, setRefresh] = useState(0);
  // "catalog" is the plain baseline: fixed catalog order, no fit guidance, same figures.
  const [mode, setMode] = useState<"guided" | "catalog">("guided");
  const requestRevision = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const currentNeed = useRef(need);
  const valid =
    Number.isInteger(need.requested_amount_rub) &&
    need.requested_amount_rub > 0 &&
    need.requested_amount_rub <= MAX_AMOUNT;

  function update(patch: Partial<Need>) {
    // Invalidate immediately, before React runs effect cleanup, so an old response
    // cannot describe freshly edited controls. The server may still save it.
    requestRevision.current += 1;
    controller.current?.abort();
    setSnapshot(null);
    setError("");
    const next = { ...currentNeed.current, ...patch };
    currentNeed.current = next;
    setNeed(next);
    setPending(true);
  }
  useEffect(() => {
    const revision = ++requestRevision.current;
    const read = new AbortController();
    controller.current = read;
    const active = () =>
      !read.signal.aborted && revision === requestRevision.current;
    setPending(true);
    setError("");
    const timer = window.setTimeout(async () => {
      if (!valid) {
        if (active()) setPending(false);
        return;
      }
      try {
        const [catalogResult, result] = await Promise.all([
          catalog
            ? Promise.resolve(catalog)
            : recommendationsApi.catalog(read.signal),
          recommendationsApi.calculate(data.company.id, need, read.signal),
        ]);
        if (!active()) return;
        setCatalog(catalogResult);
        setSnapshot(result);
      } catch (e) {
        if (active()) setError(errorMessage(e));
      } finally {
        if (active()) setPending(false);
      }
    }, 300);
    return () => {
      window.clearTimeout(timer);
      read.abort();
      requestRevision.current += 1;
    };
  }, [need, data.company.id, refresh]);

  const start = useStartApplication({
    companyId: data.company.id,
    snapshotId: snapshot?.snapshot_id ?? null,
    attempts,
    onCreated: onApplicationCreated,
    onUnauthorized,
  });
  const guided = mode === "guided";
  const cards =
    snapshot && catalog
      ? guided
        ? snapshot.items
        : catalog.products.flatMap((p) =>
            snapshot.items.filter((i) => i.product_id === p.id),
          )
      : [];
  const registry = data.company.registry_status;
  const hasTurnover = (data.precheck.monthly_revenue_rub ?? 0) > 0;
  return (
    <>
      <button className="back-link" onClick={onBack}>
        ← Профиль компании
      </button>
      <div className="page-heading detail-heading">
        <div>
          <div className="eyebrow accent">Подбор финансирования</div>
          <h1>Найдём подходящий маршрут</h1>
          <p>{data.company.name} · синтетические сведения</p>
        </div>
        <DemoBadge />
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
      {!hasTurnover && (
        <div className="notice caution">
          <Icon name="info" />
          <span>
            Нет положительных сведений об обороте: личный лимит и платёж не
            рассчитываются. Эти сведения можно дополнить в анкете.
          </span>
        </div>
      )}
      <div className="recommendation-layout">
        <section className="card need-panel" aria-labelledby="need-heading">
          <div className="eyebrow">01 / Ваша задача</div>
          <h2 id="need-heading">Какая сумма нужна?</h2>
          <label htmlFor="need-amount">Сумма, ₽</label>
          <input
            id="need-amount"
            type="number"
            min="1"
            max={MAX_AMOUNT}
            step="1"
            value={need.requested_amount_rub || ""}
            onChange={(e) =>
              update({ requested_amount_rub: e.target.valueAsNumber || 0 })
            }
          />
          <input
            className="amount-slider"
            aria-label="Изменить сумму ползунком"
            aria-valuetext={money(need.requested_amount_rub)}
            type="range"
            min="300000"
            max="6000000"
            step="50000"
            value={Math.min(
              6000000,
              Math.max(300000, need.requested_amount_rub),
            )}
            onChange={(e) =>
              update({ requested_amount_rub: Number(e.target.value) })
            }
          />
          <div className="range-labels">
            <span>300 тыс.</span>
            <span>6 млн ₽</span>
          </div>
          <p className="field-hint">
            Можно ввести от 1 ₽ до 2 млрд ₽ для сравнения с условиями
            продуктов. Цель, срок и залог укажете в анкете выбранного продукта.
          </p>
          {!valid && (
            <p className="form-error" role="alert">
              Укажите целую положительную сумму до 2 млрд ₽.
            </p>
          )}
          <div className="need-source">
            <span>
              Среднемесячный оборот <DemoBadge />
            </span>
            <strong>{money(data.precheck.monthly_revenue_rub)}</strong>
            <small>
              Личный лимит ограничен оборотом, даже при наличии залога.
            </small>
          </div>
        </section>
        <section
          className="recommendation-results"
          aria-labelledby="results-heading"
          aria-busy={pending && valid}
        >
          <div className="results-heading">
            <div>
              <div className="eyebrow">02 / Сравнение</div>
              <h2 id="results-heading">
                {guided ? "Маршруты для бизнеса" : "Каталог продуктов"}
              </h2>
            </div>
            <label className="order-select">
              Режим
              <select
                aria-label="Режим показа продуктов"
                value={mode}
                onChange={(e) => setMode(e.target.value as typeof mode)}
              >
                <option value="guided">Подбор с объяснениями</option>
                <option value="catalog">Обычный каталог</option>
              </select>
            </label>
          </div>
          {error && (
            <ErrorNotice
              error={error}
              onRetry={() => setRefresh((x) => x + 1)}
            />
          )}
          {pending && valid && (
            <div className="card calculating" role="status">
              <Icon name="refresh" />
              <span>Сравниваем параметры и пересчитываем платёж…</span>
            </div>
          )}
          {!valid && (
            <div className="card calculating">
              Заполните параметры слева, чтобы увидеть сравнение.
            </div>
          )}
          {cards.map((item) => {
            const product = catalog?.products.find(
              (p) => p.id === item.product_id,
            );
            if (!product) return null;
            return (
              <ProductCard
                key={item.product_id}
                item={item}
                product={product}
                guided={guided}
                onRecalculate={(amount) =>
                  update({ requested_amount_rub: amount })
                }
                start={{
                  pending: start.pending === item.product_id,
                  busy: start.pending !== null,
                  problem:
                    start.problem?.productId === item.product_id
                      ? start.problem.problem
                      : null,
                  onStart: () => void start.start(item.product_id),
                  // A fresh calculation saves a new snapshot under the current catalog and rules.
                  onRefresh: () => update({}),
                }}
              />
            );
          })}
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
      </div>
    </>
  );
}
