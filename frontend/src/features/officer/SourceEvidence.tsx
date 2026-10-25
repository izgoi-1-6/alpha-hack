import { ReactNode } from "react";
import { DemoBadge } from "../../components";
import { formatDateTime, rub, rubOrNone } from "../applications/format";
import { formatDay } from "../applications/fields";
import { FinanceEvidence, SourceStatus, StaffDetail } from "./officerApi";
import {
  capitalize,
  CREDIT_HISTORY,
  ORIGIN,
  SOURCE_STATUS,
} from "./officerFormat";

const REGISTRY_STATUS = {
  active: "компания действующая",
  inactive: "компания недействующая",
  unknown: "статус компании неизвестен",
};
const tone = (status: SourceStatus) =>
  status === "available" ? "success" : "warning";
/** Facts of one source, separated by «·» so dates ending in «г.» never get a second period. */
const facts = (...parts: (string | false | null | undefined)[]) =>
  capitalize(parts.filter(Boolean).join(" · "));

function SourceRow({
  name,
  status,
  children,
}: {
  name: string;
  status: SourceStatus | null;
  children: ReactNode;
}) {
  return (
    <li>
      <div className="source-head">
        <b>{name}</b>
        <span className={"status " + (status ? tone(status) : "neutral")}>
          {status ? SOURCE_STATUS[status] : "Не запрашивался"}
        </span>
        <DemoBadge />
      </div>
      <p>{children}</p>
    </li>
  );
}

/** Registry, turnover and BKI as the mocks answered them; every source is a labelled local imitation. */
export function SourcesPanel({
  evidence,
}: {
  evidence: StaffDetail["source_evidence"];
}) {
  const { company, precheck } = evidence;
  const bki = evidence.bki[evidence.bki.length - 1];
  return (
    <section className="card evidence-card" aria-labelledby="sources-heading">
      <div className="panel-title">
        <h2 id="sources-heading">Демо-источники</h2>
      </div>
      <ul className="source-list">
        <SourceRow name="Реестр" status={precheck.registry_source_status}>
          {facts(
            REGISTRY_STATUS[company.registry_status],
            company.registered_at &&
              `регистрация ${formatDay(company.registered_at)}`,
            `проверено ${formatDateTime(precheck.checked_at)}`,
          )}
        </SourceRow>
        <SourceRow name="Обороты" status={precheck.turnover_source_status}>
          {facts(
            `выручка за текущий период ${rubOrNone(precheck.monthly_revenue_rub)}`,
            `за предыдущий ${rubOrNone(precheck.previous_monthly_revenue_rub)}`,
            precheck.financial_period_end &&
              `период до ${formatDay(precheck.financial_period_end)}`,
          )}
        </SourceRow>
        <SourceRow name="БКИ" status={bki?.status ?? null}>
          {bki
            ? facts(
                `кредитная история: ${bki.credit_history ? CREDIT_HISTORY[bki.credit_history] : "категория не передана"}`,
                `текущая просрочка: ${bki.current_overdue_days !== null ? `${bki.current_overdue_days} дн.` : "нет данных"}`,
                `запрос № ${bki.attempt}`,
                bki.reused_from_evaluation_id &&
                  "ответ взят из прежней проверки",
              )
            : "Запрос в демо-БКИ по заявке не выполнялся"}
        </SourceRow>
      </ul>
    </section>
  );
}

const FINANCE_ROWS: [string, string][] = [
  ["monthly_revenue_rub", "Выручка за текущий период"],
  ["previous_monthly_revenue_rub", "Выручка за предыдущий период"],
  ["financial_period_end", "Окончание отчётного периода"],
];
const shown = (value: FinanceEvidence["answer"] | undefined) =>
  value === null || value === undefined
    ? "нет значения"
    : typeof value === "number"
      ? rub(value)
      : formatDay(value);

/** Stage-3 answers beside the source: a conflict or a declaration keeps the source's original value visible. */
export function FinancePanel({
  finance,
}: {
  finance: Record<string, FinanceEvidence>;
}) {
  return (
    <section className="card evidence-card" aria-labelledby="finance-heading">
      <div className="panel-title">
        <h2 id="finance-heading">Анкета и данные источника</h2>
      </div>
      <ul className="finance-list">
        {FINANCE_ROWS.map(([name, label]) => {
          const entry = finance[name];
          if (!entry) return null;
          const conflict =
            entry.origin === "override" || entry.origin === "declared";
          const changed =
            entry.submitted_answer !== undefined &&
            entry.submitted_answer !== entry.answer;
          return (
            <li key={name}>
              <div className="source-head">
                <b>{label}</b>
                <span
                  className={
                    "status " +
                    (conflict ? "warning" : entry.origin ? "success" : "neutral")
                  }
                >
                  {entry.origin ? ORIGIN[entry.origin] : "Нет ответа"}
                </span>
              </div>
              <dl>
                <div>
                  <dt>Анкета</dt>
                  <dd>{shown(entry.answer)}</dd>
                </div>
                {changed && (
                  <div>
                    <dt>При отправке</dt>
                    <dd>{shown(entry.submitted_answer)}</dd>
                  </div>
                )}
                <div>
                  <dt>Источник</dt>
                  <dd>
                    {shown(entry.source)} ·{" "}
                    {SOURCE_STATUS[entry.source_status].toLowerCase()}
                  </dd>
                </div>
              </dl>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
