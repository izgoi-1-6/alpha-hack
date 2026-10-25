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

const initial: Need = {
  purpose: "working_capital",
  funding_pattern: "one_time",
  requested_amount_rub: 1500000,
  term_months: 12,
  collateral: { status: "unknown" },
};

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
  const declared = need.collateral?.status === "declared";
  const valid =
    Number.isInteger(need.requested_amount_rub) &&
    need.requested_amount_rub > 0 &&
    need.requested_amount_rub <= 150000000 &&
    Number.isInteger(need.term_months) &&
    need.term_months >= 1 &&
    need.term_months <= 120 &&
    (!declared ||
      (!!need.collateral?.declared_value_rub &&
        Number.isInteger(need.collateral.declared_value_rub) &&
        !!need.collateral.description?.trim()));

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
  const supportedIds = new Set(catalog?.products.map((p) => p.id));
  // Archive entries that reuse a supported product id are superseded by the demo policy above.
  const archive = (catalog?.research_items ?? []).filter(
    (item) => !supportedIds.has(item.id),
  );
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
          запрашивается. Все ставки и условия — учебные.
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
          <h2 id="need-heading">Что нужно бизнесу?</h2>
          <label htmlFor="need-purpose">Цель финансирования</label>
          <select
            id="need-purpose"
            value={need.purpose}
            onChange={(e) =>
              update({ purpose: e.target.value as Need["purpose"] })
            }
          >
            <option value="working_capital">
              Пополнить оборотные средства
            </option>
            <option value="business_development">Развивать бизнес</option>
            <option value="investment">Инвестировать в активы</option>
            <option value="refinancing">Рефинансировать обязательства</option>
          </select>
          <fieldset className="pattern-field">
            <legend>Как понадобятся деньги?</legend>
            <div className="pattern-options">
              <label
                className={need.funding_pattern === "one_time" ? "chosen" : ""}
              >
                <input
                  type="radio"
                  name="funding"
                  value="one_time"
                  checked={need.funding_pattern === "one_time"}
                  onChange={() => update({ funding_pattern: "one_time" })}
                />
                <span>
                  <b>Одной суммой</b>
                  <small>Одна покупка или проект</small>
                </span>
              </label>
              <label
                className={need.funding_pattern === "repeated" ? "chosen" : ""}
              >
                <input
                  type="radio"
                  name="funding"
                  value="repeated"
                  checked={need.funding_pattern === "repeated"}
                  onChange={() => update({ funding_pattern: "repeated" })}
                />
                <span>
                  <b>По мере необходимости</b>
                  <small>Повторные закупки и расходы</small>
                </span>
              </label>
            </div>
          </fieldset>
          <label htmlFor="need-amount">Сумма, ₽</label>
          <input
            id="need-amount"
            type="number"
            min="1"
            max="150000000"
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
            Можно ввести от 1 ₽ до 150 млн ₽ для сравнения с условиями
            продуктов.
          </p>
          <label htmlFor="need-term">Срок, месяцев</label>
          <input
            id="need-term"
            type="number"
            min="1"
            max="120"
            step="1"
            value={need.term_months || ""}
            onChange={(e) =>
              update({ term_months: e.target.valueAsNumber || 0 })
            }
          />
          <label htmlFor="collateral-status">Есть ли залог?</label>
          <select
            id="collateral-status"
            value={need.collateral?.status ?? "unknown"}
            onChange={(e) =>
              update({
                collateral:
                  e.target.value === "declared"
                    ? {
                        status: "declared",
                        type: "real_estate",
                        description: "",
                        owner_confirmed: false,
                        encumbered: false,
                      }
                    : { status: e.target.value as "none" | "unknown" },
              })
            }
          >
            <option value="unknown">Пока не знаю</option>
            <option value="none">Без залога</option>
            <option value="declared">Могу предложить залог</option>
          </select>
          {declared && (
            <div className="collateral-fields">
              <label htmlFor="collateral-type">Тип залога</label>
              <select
                id="collateral-type"
                value={need.collateral?.type}
                onChange={(e) =>
                  update({
                    collateral: {
                      ...need.collateral!,
                      type: e.target.value as NonNullable<
                        Need["collateral"]
                      >["type"],
                    },
                  })
                }
              >
                <option value="real_estate">Недвижимость</option>
                <option value="vehicle">Транспорт</option>
                <option value="equipment">Оборудование</option>
                <option value="inventory">Товары</option>
                <option value="deposit">Депозит</option>
              </select>
              <label htmlFor="collateral-value">Заявленная стоимость, ₽</label>
              <input
                id="collateral-value"
                type="number"
                min="1"
                max="9000000000000000"
                step="1"
                value={need.collateral?.declared_value_rub || ""}
                onChange={(e) =>
                  update({
                    collateral: {
                      ...need.collateral!,
                      declared_value_rub: e.target.valueAsNumber || undefined,
                    },
                  })
                }
              />
              <label htmlFor="collateral-description">Описание залога</label>
              <input
                id="collateral-description"
                maxLength={500}
                value={need.collateral?.description || ""}
                onChange={(e) =>
                  update({
                    collateral: {
                      ...need.collateral!,
                      description: e.target.value,
                    },
                  })
                }
                placeholder="Например, демо складское помещение"
              />
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={need.collateral?.owner_confirmed || false}
                  onChange={(e) =>
                    update({
                      collateral: {
                        ...need.collateral!,
                        owner_confirmed: e.target.checked,
                      },
                    })
                  }
                />
                Подтверждаю собственность на залог
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={need.collateral?.encumbered || false}
                  onChange={(e) =>
                    update({
                      collateral: {
                        ...need.collateral!,
                        encumbered: e.target.checked,
                      },
                    })
                  }
                />
                Есть обременение
              </label>
              <p className="field-hint">
                Ваше заявление потребуется подтвердить документами. Доля
                учредителя не заменяет согласия поручителя.
              </p>
            </div>
          )}
          {!valid && (
            <p className="form-error" role="alert">
              Укажите целую положительную сумму до 150 млн ₽ и срок 1–120
              месяцев. Для залога нужны положительная целая стоимость, тип и
              описание.
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
                {guided ? "Три маршрута для бизнеса" : "Каталог продуктов"}
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
      {catalog && (
        <details className="card research-catalog">
          <summary>
            Исследовательский каталог{" "}
            <span>{archive.length} справочных позиций</span>
          </summary>
          <p>
            Архив исследования: параметры не проверены и не используются в
            расчётах. Эти продукты не принимают заявки в демо. Три записи
            архива, совпадающие с демо-продуктами выше, заменены учебными
            условиями и здесь не повторяются.
          </p>
          <ul>
            {archive.map((item) => (
              <li key={item.id}>
                <span>{item.name}</span>
                <span className="status neutral">Только справочно</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
