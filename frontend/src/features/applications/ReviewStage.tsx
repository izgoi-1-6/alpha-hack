import { useState } from "react";
import { ConsentDocument, Dialog, FieldDescriptor } from "../../api";
import { DemoBadge, Icon } from "../../components";
import { CommandProblem } from "./commands";
import { FieldDraft, formatAnswer, locate } from "./fields";
import { keepAmountsTogether } from "./format";
import { StageField } from "./StageFields";

const CONSENT_TITLES: Record<string, string> = {
  APPLICATION_PROCESSING: "Обработка данных заявки",
  BKI: "Запрос кредитной истории в демо-БКИ",
};
const ORIGINS: Record<string, string> = {
  source: "из демо-источника",
  override: "изменено вами — проверит специалист",
  declared: "заявлено вами — проверит специалист",
};

function SubmitProblem({
  problem,
  onJump,
  onRecalculate,
  onOpenApplication,
  dialog,
}: {
  problem: CommandProblem;
  onJump: (stage: number) => void;
  onRecalculate: () => void;
  onOpenApplication: (id: string) => void;
  dialog: Dialog;
}) {
  const fields = Object.keys(problem.fields).filter(
    (path) => path !== "consents",
  );
  return (
    <div className="notice error submit-problem" role="alert">
      <Icon name="info" />
      <div>
        <p>{keepAmountsTogether(problem.message)}</p>
        {fields.length > 0 && (
          <ul>
            {fields.map((path) => {
              const place = locate(dialog.stages, path);
              return (
                <li key={path}>
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => onJump(place.stage)}
                  >
                    {place.label}
                  </button>{" "}
                  · шаг {place.stage}
                </li>
              );
            })}
          </ul>
        )}
        {problem.kind === "stale" && (
          <button
            type="button"
            className="button secondary"
            onClick={onRecalculate}
          >
            <Icon name="refresh" size={17} />
            Пересчитать оценку
          </button>
        )}
        {problem.kind === "duplicate" && problem.activeApplicationId && (
          <button
            type="button"
            className="button secondary"
            onClick={() => onOpenApplication(problem.activeApplicationId!)}
          >
            Открыть заявку в работе
            <Icon />
          </button>
        )}
      </div>
    </div>
  );
}

/** Stage 6: every saved answer with a way back to its stage, the accuracy confirmation and the two consents. */
export function ReviewStage({
  dialog,
  consents,
  accuracy,
  accuracyDraft,
  onAccuracy,
  busy,
  submitting,
  problem,
  onBack,
  onJump,
  onSubmit,
  onRecalculate,
  onOpenApplication,
}: {
  dialog: Dialog;
  consents: ConsentDocument[];
  accuracy: FieldDescriptor;
  accuracyDraft: FieldDraft;
  onAccuracy: (draft: FieldDraft) => void;
  busy: boolean;
  submitting: boolean;
  problem: CommandProblem | null;
  onBack: () => void;
  onJump: (stage: number) => void;
  onSubmit: (consents: ConsentDocument[]) => void;
  onRecalculate: () => void;
  onOpenApplication: (id: string) => void;
}) {
  // Consents live only in this view: never pre-checked and never kept between visits.
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const blockers = Object.entries(dialog.field_issues)
    .filter(([path]) => path !== accuracy.name)
    .map(([path, message]) => ({
      path,
      message,
      ...locate(dialog.stages, path),
    }));
  const canSubmit = dialog.allowed_actions.includes("submit");
  const confirmed = accuracyDraft === true;
  const consented =
    consents.length === 2 && consents.every((doc) => accepted[doc.code]);
  const remaining = [
    blockers.length > 0 && `заполнить обязательные поля (${blockers.length})`,
    !confirmed && "подтвердить точность сведений",
    !consented && "отметить оба согласия",
  ].filter(Boolean);
  const ready = canSubmit && remaining.length === 0 && !busy;

  return (
    <>
      <div className="review">
        {dialog.stages
          .filter((stage) => stage.number < dialog.steps_total)
          .map((stage) => (
            <section
              key={stage.number}
              className="review-section"
              aria-labelledby={`review-${stage.number}`}
            >
              <div className="review-head">
                <h3 id={`review-${stage.number}`}>
                  <span aria-hidden="true">{stage.number}</span>
                  {stage.title}
                </h3>
                <span
                  className={
                    "review-state " + (stage.complete ? "done" : "todo")
                  }
                >
                  {stage.complete ? "Заполнено" : "Нужно дополнить"}
                </span>
                <button
                  type="button"
                  className="button secondary"
                  aria-label={`Изменить шаг ${stage.number}: ${stage.title}`}
                  onClick={() => onJump(stage.number)}
                  disabled={busy}
                >
                  Изменить
                </button>
              </div>
              <dl>
                {stage.fields.map((field) => {
                  const shown = formatAnswer(field, dialog.answers[field.name]);
                  return (
                    <div key={field.name}>
                      <dt>{field.label}</dt>
                      <dd>
                        {shown ??
                          (field.required ? (
                            <span className="missing">Не заполнено</span>
                          ) : (
                            <span className="unset">Не указано</span>
                          ))}
                        {shown && field.origin && (
                          <small className="origin">
                            {ORIGINS[field.origin]}
                          </small>
                        )}
                      </dd>
                    </div>
                  );
                })}
              </dl>
            </section>
          ))}
      </div>

      {blockers.length > 0 && (
        <div className="notice caution review-blockers">
          <Icon name="info" />
          <div>
            <strong>Чтобы отправить заявку, дополните анкету</strong>
            <ul>
              {blockers.map((blocker) => (
                <li key={blocker.path}>
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => onJump(blocker.stage)}
                    disabled={busy}
                  >
                    {blocker.label}
                  </button>{" "}
                  · шаг {blocker.stage}: {keepAmountsTogether(blocker.message)}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <StageField
        field={accuracy}
        draft={accuracyDraft}
        messages={{}}
        disabled={busy}
        onChange={onAccuracy}
      />

      <fieldset className="consents-block">
        <legend>Согласия для отправки</legend>
        <p className="field-note">
          Каждое согласие отмечается отдельно. Кредитная история запрашивается в
          демо-БКИ только после отправки заявки.
        </p>
        {consents.map((doc) => (
          <label key={doc.code} className="check-row consent-row">
            <input
              type="checkbox"
              checked={!!accepted[doc.code]}
              disabled={busy}
              onChange={(event) =>
                setAccepted({ ...accepted, [doc.code]: event.target.checked })
              }
            />
            <span>
              <b>
                {CONSENT_TITLES[doc.code] ?? doc.code}
                {doc.code === "BKI" && <DemoBadge />}
              </b>
              {doc.text}
              <small>Версия {doc.version}</small>
            </span>
          </label>
        ))}
      </fieldset>

      {problem && (
        <SubmitProblem
          problem={problem}
          dialog={dialog}
          onJump={onJump}
          onRecalculate={onRecalculate}
          onOpenApplication={onOpenApplication}
        />
      )}
      <div className="submit-bar">
        <button
          type="button"
          className="button secondary"
          onClick={onBack}
          disabled={busy}
        >
          ← Назад
        </button>
        <p id="submit-state" className="submit-state">
          {!canSubmit
            ? dialog.company.registry_status === "inactive"
              ? "Компания не действует по данным демо-реестра: отправить заявку нельзя."
              : "Отправка этой заявки недоступна."
            : remaining.length
              ? `Осталось: ${remaining.join("; ")}.`
              : "Всё готово. После отправки демо-БКИ запросит кредитную историю, и вы сразу увидите результат проверки."}
        </p>
        {canSubmit && (
          <button
            type="button"
            className="button primary"
            disabled={!ready}
            aria-describedby="submit-state"
            onClick={() => onSubmit(consents)}
          >
            {submitting ? "Отправляем…" : "Отправить заявку"}
            <Icon />
          </button>
        )}
      </div>
    </>
  );
}
