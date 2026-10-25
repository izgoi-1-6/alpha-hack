import { DemoBadge } from "../../components";
import {
  formatDate,
  formatDateTime,
  keepAmountsTogether,
  points,
  RISK,
  rub,
  rubOrNone,
  signedRub,
  STATUS,
} from "../applications/format";
import { Amount } from "../applications/Amount";
import { EvaluationRecord, StaffApplication, StaffEvaluation } from "./officerApi";
import {
  capitalize,
  CREDIT_HISTORY,
  REVIEW_FLAGS,
  RISK_TONE,
} from "./officerFormat";

/** Requested amount, scored limit, their difference and the officer's inclusive preapproval range (or its refusal). */
export function ReviewAmounts({
  application,
}: {
  application: StaffApplication;
}) {
  const requested = application.requested_amount_rub;
  const evaluation = application.latest_evaluation;
  const limit = evaluation?.scored_limit_rub ?? null;
  const difference =
    requested !== null && limit !== null ? requested - limit : null;
  const term = application.answers.term_months;
  const preapproval = application.preapproval;
  return (
    <div className="amounts review-amounts">
      <Amount
        label="Запрошенная сумма"
        value={requested !== null ? rub(requested) : "Не указана"}
        note={`${typeof term === "number" ? `Срок ${term} мес. ` : ""}Решение специалиста её не меняет.`}
      />
      <Amount
        label="Расчётный лимит"
        value={limit !== null ? rub(limit) : "Не рассчитан"}
        note={
          evaluation
            ? `Демо-скоринг, правило ${evaluation.rule}.`
            : "Проверка не проводилась."
        }
      />
      <Amount
        label="Разница с лимитом"
        value={difference !== null ? signedRub(difference) : "—"}
        tone={difference !== null && difference > 0 ? "caution" : undefined}
        note={
          difference === null
            ? "Без расчётного лимита разницу не определить."
            : difference > 0
              ? "Запрошено больше расчётного лимита."
              : "Запрос в пределах расчётного лимита."
        }
      />
      {preapproval &&
        (preapproval.blocked_by ? (
          <Amount
            label="Допустимая сумма одобрения"
            value="Недоступно"
            tone="blocked"
            note={keepAmountsTogether(preapproval.blocked_by.message)}
          />
        ) : (
          preapproval.amount_min_rub !== null &&
          preapproval.amount_max_rub !== null && (
            <Amount
              label="Допустимая сумма одобрения"
              value={`до ${rub(preapproval.amount_max_rub)}`}
              note={`от ${rub(preapproval.amount_min_rub)} (минимум продукта) до меньшего из запрошенной суммы и расчётного лимита, границы включительно.`}
            />
          )
        ))}
      {application.preapproved_amount_rub !== null && (
        <Amount
          label="Предварительно одобрено"
          tone="preapproved"
          value={rub(application.preapproved_amount_rub)}
          note={
            application.final_amount_rub !== null
              ? "Решение до проверки документов."
              : `Не окончательное решение.${application.preapproval_expires_at ? ` Срок документов — до ${formatDate(application.preapproval_expires_at)}` : ""}`
          }
        />
      )}
      <FinalAmounts application={application} />
    </div>
  );
}

/** The document phase: the inclusive final range from accepted evidence (or why it is refused), then the decision. */
function FinalAmounts({ application }: { application: StaffApplication }) {
  const terms = application.final_approval;
  return (
    <>
      {terms &&
        (terms.blocked_by ? (
          <Amount
            label="Допустимая итоговая сумма"
            value="Недоступно"
            tone="blocked"
            note={keepAmountsTogether(terms.blocked_by.message)}
          />
        ) : (
          terms.amount_min_rub !== null &&
          terms.amount_max_rub !== null && (
            <Amount
              label="Допустимая итоговая сумма"
              value={`до ${rub(terms.amount_max_rub)}`}
              note={`от ${rub(terms.amount_min_rub)} до меньшего из предварительно одобренной суммы и лимита по проверенным документам${terms.verified_limit_rub !== null ? ` (${rub(terms.verified_limit_rub)})` : ""}, границы включительно.`}
            />
          )
        ))}
      {application.final_amount_rub !== null && (
        <Amount
          label="Итоговая сумма (демо-решение)"
          tone="approved"
          value={rub(application.final_amount_rub)}
          note="Окончательное решение демо: деньги не перечисляются, договор не подписывается."
        />
      )}
    </>
  );
}

const numberAt = (value: unknown) =>
  typeof value === "number" ? value : null;

/** The latest evaluation: total, risk, the rule, each factor with its points, review flags and the server's reasons. */
export function ScorePanel({
  evaluation,
}: {
  evaluation: EvaluationRecord | undefined;
}) {
  const factors = evaluation?.factors;
  const finance = evaluation?.input_snapshot.finance ?? {};
  const revenue = numberAt(finance.monthly_revenue_rub?.value);
  const previous = numberAt(finance.previous_monthly_revenue_rub?.value);
  const debt = numberAt(
    evaluation?.input_snapshot.answers?.monthly_debt_payment_rub,
  );
  // Factor maxima are the spec's original scoring table (age 20, growth 25, burden 30, history 25).
  const rows: [string, string, number, number][] = factors
    ? [
        ["Возраст бизнеса", `${factors.age_months} мес.`, factors.age_points, 20],
        [
          "Динамика выручки",
          `${rubOrNone(revenue)} к ${rubOrNone(previous)} за прошлый период`,
          factors.revenue_growth_points,
          25,
        ],
        [
          "Долговая нагрузка",
          `${rubOrNone(debt)} в месяц при выручке ${rubOrNone(revenue)}`,
          factors.debt_burden_points,
          30,
        ],
        [
          "Кредитная история (демо-БКИ)",
          CREDIT_HISTORY[factors.credit_history],
          factors.credit_history_points,
          25,
        ],
      ]
    : [];
  return (
    <section className="card evidence-card" aria-labelledby="score-heading">
      <div className="panel-title">
        <h2 id="score-heading">Скоринг и факторы</h2>
        <DemoBadge label="Демо-скоринг" />
      </div>
      {!evaluation ? (
        <p className="muted">Проверка по заявке не проводилась.</p>
      ) : (
        <>
          <div className="score-summary">
            <strong>
              {evaluation.score !== null
                ? `${points(evaluation.score)} из 100`
                : "Балл не рассчитан"}
            </strong>
            {evaluation.risk && (
              <span className={"status " + RISK_TONE[evaluation.risk]}>
                {capitalize(RISK[evaluation.risk])}
              </span>
            )}
            <span className="score-rule">
              Правило {evaluation.rule} · итог «{STATUS[evaluation.outcome].label}»
            </span>
          </div>
          {rows.length > 0 && (
            <table className="factor-table">
              <thead>
                <tr>
                  <th scope="col">Фактор</th>
                  <th scope="col">Данные</th>
                  <th scope="col" className="num">
                    Баллы
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map(([label, data, value, max]) => (
                  <tr key={label}>
                    <th scope="row">{label}</th>
                    <td>{data}</td>
                    <td className="num">
                      {value} из {max}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <Flags evaluation={evaluation} />
          <ul className="result-reasons">
            {evaluation.reasons.map((reason) => (
              <li key={reason}>{keepAmountsTogether(reason)}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function Flags({ evaluation }: { evaluation: StaffEvaluation }) {
  if (evaluation.review_flags.length === 0) return null;
  return (
    <div className="flag-list" aria-label="Причины ручной проверки">
      {evaluation.review_flags.map((flag) => (
        <span key={flag} className="status warning">
          {REVIEW_FLAGS[flag] ?? flag}
        </span>
      ))}
    </div>
  );
}

/** Every evaluation, newest first; each is an immutable record of one check. */
export function EvaluationsPanel({
  evaluations,
}: {
  evaluations: EvaluationRecord[];
}) {
  const newestFirst = [...evaluations].reverse();
  return (
    <section
      className="card evidence-card"
      aria-labelledby="evaluations-heading"
    >
      <div className="panel-title">
        <h2 id="evaluations-heading">Проверки по заявке</h2>
      </div>
      <p className="panel-note">
        Каждая проверка сохраняется без изменений; первая в списке — актуальная.
      </p>
      {newestFirst.length === 0 ? (
        <p className="muted">Проверок пока не было.</p>
      ) : (
        <ol className="evaluation-list">
          {newestFirst.map((evaluation, index) => {
            const bki = evaluation.sources.bki as
              | { reused_from_evaluation_id?: string }
              | undefined;
            return (
              <li key={evaluation.id}>
                <div className="record-head">
                  <strong>{formatDateTime(evaluation.created_at)}</strong>
                  {index === 0 && (
                    <span className="status neutral">Актуальная</span>
                  )}
                </div>
                <p>
                  Правило {evaluation.rule} → {STATUS[evaluation.outcome].label}
                  {" · "}
                  {evaluation.score !== null
                    ? `${points(evaluation.score)}`
                    : "балл не рассчитан"}
                  {evaluation.risk ? `, ${RISK[evaluation.risk]}` : ""}
                  {" · "}
                  {evaluation.scored_limit_rub !== null
                    ? `лимит ${rub(evaluation.scored_limit_rub)}`
                    : "лимит не рассчитан"}
                </p>
                {bki?.reused_from_evaluation_id && (
                  <small>
                    Ответ демо-БКИ взят из прежней проверки: повторного запроса
                    не было.
                  </small>
                )}
                <ul>
                  {evaluation.reasons.map((reason) => (
                    <li key={reason}>{keepAmountsTogether(reason)}</li>
                  ))}
                </ul>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
