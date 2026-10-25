import { ReactNode } from "react";
import { Application, Dialog, DialogStage } from "../../api";
import { DemoBadge, Icon } from "../../components";
import { rub } from "./format";

/** Progress as a slim bar with a textual count, and one 44px button per stage (titles collapse on small screens). */
export function Stepper({
  stages,
  stage,
  busy,
  onGo,
}: {
  stages: DialogStage[];
  stage: number;
  busy: boolean;
  onGo: (stage: number) => void;
}) {
  const completed = stages.filter((entry) => entry.complete).length;
  return (
    <div className="wizard-progress">
      <div className="progress-line">
        <div
          className="progress-bar"
          role="progressbar"
          aria-label="Заполнено шагов анкеты"
          aria-valuemin={0}
          aria-valuemax={stages.length}
          aria-valuenow={completed}
          aria-valuetext={`Заполнено ${completed} из ${stages.length}`}
        >
          <span style={{ width: `${(completed / stages.length) * 100}%` }} />
        </div>
        <p>
          Заполнено {completed} из {stages.length} шагов
        </p>
      </div>
      <nav aria-label="Шаги анкеты">
        <ol className="stepper">
          {stages.map((entry) => (
            <li key={entry.number}>
              <button
                type="button"
                className={
                  (entry.number === stage ? "current " : "") +
                  (entry.complete ? "complete" : "")
                }
                aria-current={entry.number === stage ? "step" : undefined}
                aria-label={`Шаг ${entry.number}: ${entry.title}${entry.complete ? ", заполнен" : ""}`}
                disabled={busy}
                onClick={() => onGo(entry.number)}
              >
                <span className="step-mark" aria-hidden="true">
                  {entry.complete && entry.number !== stage ? (
                    <Icon name="check" size={16} />
                  ) : (
                    entry.number
                  )}
                </span>
                <span className="step-title" aria-hidden="true">
                  {entry.title}
                </span>
              </button>
            </li>
          ))}
        </ol>
      </nav>
    </div>
  );
}

/** The saved need and the preliminary figures beside the questionnaire; nothing here is an offer. */
export function DraftSummary({
  application,
  dialog,
  cancel,
}: {
  application: Application;
  dialog: Dialog;
  cancel: ReactNode;
}) {
  const fields = dialog.stages.flatMap((entry) => entry.fields);
  const purpose = fields
    .find((field) => field.name === "purpose")
    ?.options?.find((option) => option.value === dialog.answers.purpose)?.label;
  const revenue = fields.find((field) => field.name === "monthly_revenue_rub")
    ?.source?.value;
  const amount = dialog.answers.requested_amount_rub;
  const term = dialog.answers.term_months;
  const product = dialog.product;
  return (
    <aside className="card draft-summary" aria-labelledby="draft-summary-title">
      <div className="panel-title">
        <h2 id="draft-summary-title">Предварительный расчёт</h2>
        <DemoBadge />
      </div>
      <dl>
        <div>
          <dt>Продукт</dt>
          <dd>
            {product.name ?? "Демо-продукт"}
            {product.amount_min_rub != null &&
              product.amount_max_rub != null && (
                <small>
                  <span className="nowrap">
                    {rub(product.amount_min_rub)} –{" "}
                    {rub(product.amount_max_rub)}
                  </span>{" "}
                  ·{" "}
                  <span className="nowrap">
                    {product.term_min_months}–{product.term_max_months} мес.
                  </span>
                </small>
              )}
          </dd>
        </div>
        <div>
          <dt>Цель</dt>
          <dd>{purpose ?? "Не указана"}</dd>
        </div>
        <div>
          <dt>Сумма</dt>
          <dd>{typeof amount === "number" ? rub(amount) : "Не указана"}</dd>
        </div>
        <div>
          <dt>Срок</dt>
          <dd>{typeof term === "number" ? `${term} мес.` : "Не указан"}</dd>
        </div>
        <div>
          <dt>Оборот в месяц</dt>
          <dd>
            {typeof revenue === "number" ? rub(revenue) : "Нет данных"}
            <small>по демо-источнику</small>
          </dd>
        </div>
      </dl>
      <div className="summary-estimate">
        <span>Предварительная оценка по обороту</span>
        <strong>
          {application.indicative_limit_rub !== null
            ? rub(application.indicative_limit_rub)
            : "Нужно уточнить"}
        </strong>
        <small>
          Не предодобрение и не предложение. Кредитная история до отправки не
          запрашивается.
        </small>
      </div>
      {cancel}
    </aside>
  );
}
