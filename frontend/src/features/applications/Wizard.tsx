import { useEffect, useRef, useState } from "react";
import {
  AnswerValue,
  Application,
  applicationsApi,
  Collateral,
  ConsentDocument,
  Dialog,
  FieldDescriptor,
} from "../../api";
import { Icon } from "../../components";
import { CancelAction } from "./CancelAction";
import {
  CommandAttempts,
  CommandProblem,
  commandProblem,
  unknownOutcome,
} from "./commands";
import {
  answerPaths,
  FieldDraft,
  fromDraft,
  hasAnswer,
  locate,
  sameAnswer,
  termFor,
  toDraft,
} from "./fields";
import { formatTime, productName, STATUS } from "./format";
import { ReviewStage } from "./ReviewStage";
import { idOf, ProductFacts, StageField } from "./StageFields";
import { UnsavedFieldsDialog, UnsavedLeaveDialog } from "./UnsavedFieldsDialog";
import { useCommand } from "./useCommand";
import { DraftSummary, Stepper } from "./WizardChrome";

/** Resolves true once the open questionnaire may be left: its edits saved, or the customer chose to drop a value. */
export type LeaveGuard = () => Promise<boolean>;

const STAGE_INTRO: Record<number, string> = {
  1: "Подтвердите сведения из реестра и укажите, где и чем фактически занимается бизнес.",
  2: "Сумма перенесена из подбора. Выберите цель и срок в пределах условий продукта — и залог, если продукт его предусматривает.",
  3: "Обороты подставлены из источника данных: если меняете значение, его проверит кредитный специалист. Налоговый режим и число сотрудников приходят из открытых источников.",
  4: "Текущие платежи и налоговые обязательства. Кредитную историю запросим в бюро кредитных историй только после отправки.",
  5: "ФИО и полномочия представителя приходят из подтверждения через Госуслуги. Подтвердите сведения о владельцах.",
  6: "Проверьте ответы и дайте согласия — без них заявку не отправить.",
};
const belongsTo = (path: string, name: string) =>
  path === name || path.startsWith(name + ".");
/** After a refused save, focus the first input it names (once the inputs are enabled again). */
const focusFirst = (paths: string[]) =>
  window.requestAnimationFrame(() => {
    if (paths.length) document.getElementById(idOf(paths[0]))?.focus();
  });

/**
 * The six saved stages of a DRAFT. The server's dialog decides the fields, completion and blockers; this component
 * owns the local edits of the open stage. Every stage change saves those edits with the current version, so a reload
 * resumes at the saved stage. A stale version reloads and keeps the unsaved edits on screen. Leaving the questionnaire
 * (any App navigation, browser history, logout) goes through the registered leave guard, which saves the open stage
 * first; a value that cannot be saved is never dropped without the customer's explicit choice.
 */
export function Wizard({
  application,
  dialog,
  consents,
  attempts,
  refresh,
  announce,
  onOpenList,
  onOpenApplication,
  onRecalculate,
  registerLeaveGuard,
  onUnauthorized,
}: {
  application: Application;
  dialog: Dialog;
  consents: ConsentDocument[];
  attempts: CommandAttempts;
  /** Reloads the application; resolves to the fresh dialog while it is still a draft, otherwise null. */
  refresh: (notice?: string) => Promise<Dialog | null>;
  announce: (text: string) => void;
  onOpenList: () => void;
  onOpenApplication: (id: string) => void;
  onRecalculate: (companyId: string) => void;
  registerLeaveGuard: (guard: LeaveGuard | null) => void;
  onUnauthorized: () => void;
}) {
  const [stage, setStage] = useState(dialog.current_stage);
  const [edits, setEdits] = useState<Record<string, FieldDraft>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [visited, setVisited] = useState<number[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveProblem, setSaveProblem] = useState<CommandProblem | null>(null);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [prompt, setPrompt] = useState<
    { path: string; label: string; message: string }[] | null
  >(null);
  const answerPrompt = useRef<((proceed: boolean) => void) | null>(null);
  // Leaving after a failed save: the reason shown, and the answer the leave guard waits for.
  const [leavePrompt, setLeavePrompt] = useState<string | null>(null);
  const leaveAnswer = useRef<((leave: boolean) => void) | null>(null);
  // Why the last save failed, if it did; a stage move resets it.
  const failedSave = useRef<string | null>(null);
  // A leave asked while a save or the submission runs waits until it has finished; `settled` counts finished runs.
  const waitingLeave = useRef<((ok: boolean) => void) | null>(null);
  const [settled, setSettled] = useState(0);
  const submission = useCommand(attempts, onUnauthorized);
  const alive = submission.alive;
  const heading = useRef<HTMLHeadingElement>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  useEffect(() => {
    if (focusRequest) heading.current?.focus();
  }, [focusRequest]);

  const current =
    dialog.stages.find((entry) => entry.number === stage) ?? dialog.stages[0];
  const total = dialog.steps_total;
  const busy = saving || !!submission.busy;
  const unsaved = Object.keys(edits).length > 0;
  // Reloading or closing the tab with unsaved edits of the open stage asks first.
  useEffect(() => {
    if (!unsaved) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [unsaved]);
  const draftOf = (field: FieldDescriptor) =>
    field.name in edits
      ? edits[field.name]
      : toDraft(field, dialog.answers[field.name]);
  /** The field as shown: a term's range follows the purpose being chosen on the same stage. */
  function shown(field: FieldDescriptor) {
    if (field.name !== "term_months") return { field, scope: undefined };
    const purposeField = current.fields.find(
      (entry) => entry.name === "purpose",
    );
    const purpose = purposeField
      ? (draftOf(purposeField) as string | null)
      : null;
    const label = purposeField?.options?.find(
      (o) => o.value === purpose,
    )?.label;
    return termFor(field, purpose, dialog.product.term_max_months, label);
  }

  function change(field: FieldDescriptor, draft: FieldDraft) {
    setEdits((previous) => ({ ...previous, [field.name]: draft }));
    setErrors((previous) =>
      Object.fromEntries(
        Object.entries(previous).filter(
          ([path]) => !belongsTo(path, field.name),
        ),
      ),
    );
  }

  /** Input errors always; the server's blockers for a saved value, or for any gap once the stage was left. */
  function messagesFor(field: FieldDescriptor) {
    const messages: Record<string, string> = {};
    const showGaps =
      hasAnswer(field, dialog.answers[field.name]) || visited.includes(stage);
    if (!(field.name in edits) && showGaps)
      for (const [path, message] of Object.entries(dialog.field_issues))
        if (belongsTo(path, field.name)) messages[path] = message;
    for (const [path, message] of Object.entries(errors))
      if (belongsTo(path, field.name)) messages[path] = message;
    return messages;
  }

  /** Shows why a save failed and returns that message (null when there is nothing left to say: a lost session, or
   * the questionnaire is no longer a draft). */
  async function recover(error: unknown): Promise<string | null> {
    const problem = commandProblem(error);
    if (problem.kind === "session") {
      onUnauthorized();
      return null;
    }
    if (problem.kind === "version" || problem.kind === "status") {
      const fresh = await refresh(
        "Анкета уже отправлена или отменена в другой вкладке: изменения не сохранены.",
      );
      if (!alive.current || !fresh) return null;
      const message =
        "Заявка изменилась в другой вкладке или окне. Мы загрузили сохранённую версию и оставили ваши несохранённые изменения в форме — проверьте их и сохраните снова.";
      setSaveProblem({ ...problem, message });
      return message;
    }
    if (problem.kind === "fields") {
      const paths = answerPaths(problem.fields);
      setErrors((previous) => ({ ...previous, ...paths }));
      focusFirst(Object.keys(paths));
    }
    const shown =
      problem.kind === "network"
        ? {
            ...problem,
            message: unknownOutcome(
              problem,
              "Ответы этого шага не сохранены — повторите попытку.",
            ),
          }
        : problem;
    setSaveProblem(shown);
    return shown.message;
  }

  /** The open stage's changed answers; values that cannot be saved are reported and, if dropped, left as saved. */
  function collect(dropInvalid: boolean) {
    const patch: Record<string, AnswerValue> = {};
    const found: Record<string, string> = {};
    for (const field of current.fields) {
      if (!(field.name in edits)) continue;
      const saved = dialog.answers[field.name];
      const parsed = fromDraft(field, edits[field.name]);
      const invalid = Object.keys(parsed.errors);
      Object.assign(found, parsed.errors);
      let value = parsed.value;
      if (invalid.length) {
        if (!dropInvalid || field.type !== "collateral") continue;
        // A pledge keeps its valid details; an unsaveable detail keeps its saved value.
        const kept: Collateral =
          saved && typeof saved === "object" ? saved : {};
        value = { ...(value as Collateral) };
        for (const path of invalid) {
          const key = path.split(".")[1] as keyof Collateral;
          (value as Record<string, unknown>)[key] = kept[key] ?? null;
        }
      }
      if (!sameAnswer(field, value, saved)) patch[field.name] = value;
    }
    return { patch, found };
  }

  /** Lets the customer choose between fixing unsaveable values and moving on without them. */
  function ask(found: Record<string, string>) {
    return new Promise<boolean>((resolve) => {
      answerPrompt.current = resolve;
      setPrompt(
        Object.entries(found).map(([path, message]) => ({
          path,
          message,
          label: locate(dialog.stages, path).label,
        })),
      );
    });
  }
  function settlePrompt(proceed: boolean) {
    const resolve = answerPrompt.current;
    answerPrompt.current = null;
    setPrompt(null);
    resolve?.(proceed);
  }
  // A questionnaire that disappears with the question open has not been left by choice.
  useEffect(() => () => answerPrompt.current?.(false), []);

  /** Saves the open stage's changed answers and the stage pointer; resolves to the fresh dialog. */
  async function save(
    target: number,
    dropInvalid = false,
  ): Promise<Dialog | null> {
    const { patch, found } = collect(dropInvalid);
    if (!dropInvalid && Object.keys(found).length) {
      setErrors((previous) => ({ ...previous, ...found }));
      setSaveProblem({
        kind: "fields",
        message: "Проверьте отмеченные поля: шаг не сохранён.",
        fields: found,
      });
      focusFirst(Object.keys(found));
      return null;
    }
    setSaveProblem(null);
    if (!Object.keys(patch).length && target === dialog.current_stage) {
      setEdits({});
      setErrors({});
      return dialog;
    }
    setSaving(true);
    try {
      await applicationsApi.saveAnswers(dialog.application_id, {
        version: dialog.version,
        current_stage: target,
        answers: patch,
      });
    } catch (error) {
      if (!alive.current) return null;
      setSaving(false);
      failedSave.current = await recover(error);
      return null;
    }
    const fresh = await refresh();
    if (!alive.current) return null;
    setSaving(false);
    if (!fresh) return null;
    setEdits({});
    setErrors({});
    setSavedAt(new Date());
    return fresh;
  }

  /** Saves before a stage change or leaving; an unsaveable value is fixed or explicitly left out first. */
  async function move(target: number): Promise<Dialog | null> {
    failedSave.current = null;
    const { found } = collect(false);
    if (!Object.keys(found).length) return save(target);
    setErrors((previous) => ({ ...previous, ...found }));
    const proceed = await ask(found);
    if (!alive.current) return null;
    if (!proceed) {
      setSaveProblem({
        kind: "fields",
        message: "Исправьте отмеченные поля, чтобы сохранить шаг.",
        fields: found,
      });
      focusFirst(Object.keys(found));
      return null;
    }
    return save(target, true);
  }

  async function go(target: number, highlight = false) {
    if (busy || target === stage || target < 1 || target > total) return;
    const leaving = stage;
    try {
      const fresh = await move(target);
      if (!fresh || !alive.current) return;
      setVisited((previous) => [
        ...new Set([...previous, leaving, ...(highlight ? [target] : [])]),
      ]);
      setStage(target);
      setFocusRequest((n) => n + 1);
      const title = fresh.stages.find((entry) => entry.number === target)?.title;
      announce(`Сохранено. Шаг ${target} из ${total}: ${title}.`);
    } finally {
      if (alive.current) setSettled((n) => n + 1);
    }
  }

  /** Asks whether to leave without the open stage's answers after their save failed. */
  function askLeave(message: string) {
    return new Promise<boolean>((resolve) => {
      leaveAnswer.current = resolve;
      setLeavePrompt(message);
    });
  }
  function settleLeave(leave: boolean) {
    const resolve = leaveAnswer.current;
    leaveAnswer.current = null;
    setLeavePrompt(null);
    resolve?.(leave);
  }

  /**
   * The leave guard: nothing to keep, or the open stage saved (an unsaveable value fixed or knowingly left out). A
   * save that fails on the way out asks whether to leave without it, so leaving (logout included) is never refused
   * outright; a leave asked during a save or the submission waits for it to finish.
   */
  async function confirmLeave(): Promise<boolean> {
    if (prompt || leavePrompt) return false;
    if (busy)
      return new Promise<boolean>((resolve) => {
        waitingLeave.current = resolve;
      });
    if (!unsaved) return true;
    if ((await move(stage)) !== null) return true;
    const failure = failedSave.current;
    if (!alive.current || !failure) return false;
    return askLeave(failure);
  }
  const guard = useRef(confirmLeave);
  guard.current = confirmLeave;
  useEffect(() => {
    registerLeaveGuard(() => guard.current());
    return () => registerLeaveGuard(null);
  }, []);
  // A save or the submission has finished: the leave that waited for it decides on what it left behind.
  useEffect(() => {
    const resolve = waitingLeave.current;
    if (!resolve || busy) return;
    waitingLeave.current = null;
    void guard.current().then(resolve);
  }, [settled]);
  // A questionnaire that disappears meanwhile (submitted, or the session ended) has nothing left to keep.
  useEffect(
    () => () => {
      waitingLeave.current?.(true);
      leaveAnswer.current?.(false);
    },
    [],
  );

  async function submit(documents: ConsentDocument[]) {
    if (busy) return;
    try {
      await submitNow(documents);
    } finally {
      if (alive.current) setSettled((n) => n + 1);
    }
  }
  async function submitNow(documents: ConsentDocument[]) {
    const fresh = await save(total);
    if (!fresh || !alive.current) return;
    const body = {
      version: fresh.version,
      consents: documents.map((doc) => ({
        code: doc.code,
        version: doc.version,
        accepted: true as const,
      })),
    };
    const result = await submission.run(
      "submit",
      `submit:${fresh.application_id}`,
      body,
      (key) => applicationsApi.submit(fresh.application_id, body, key),
    );
    if (!result) return;
    if (result.ok) {
      announce(
        `Заявка отправлена. Статус: ${STATUS[result.value.application.status].label}.`,
      );
      await refresh();
      return;
    }
    const { problem } = result;
    if (problem.kind === "network")
      submission.setProblem({
        ...problem,
        message: unknownOutcome(
          problem,
          "Заявка могла уже отправиться: нажмите «Отправить заявку» ещё раз — повтор не создаст вторую заявку.",
        ),
      });
    else if (problem.kind === "version" || problem.kind === "status")
      await refresh("Заявка уже отправлена или отменена в другой вкладке.");
    else if (problem.kind === "fields") await refresh();
  }

  const accuracy = dialog.stages[total - 1]?.fields[0];
  const stageProblem = saveProblem ?? submission.problem;
  return (
    <div className="wizard">
      <button
        type="button"
        className="back-button"
        onClick={onOpenList}
        disabled={busy}
      >
        ← Мои заявки
      </button>
      <div className="page-heading wizard-header">
        <div>
          <div className="eyebrow accent">Анкета · черновик</div>
          <h1>{productName(dialog)}</h1>
          <p>
            {dialog.company.name} · ИНН {dialog.company.inn}
          </p>
        </div>
        <div className="wizard-header-side">
          <span className={"status status-pill " + STATUS[dialog.status].tone}>
            {STATUS[dialog.status].label}
          </span>
          <p className="save-state">
            {savedAt
              ? `Черновик сохранён в ${formatTime(savedAt)}`
              : "Ответы сохраняются при переходе между шагами и при выходе"}
          </p>
        </div>
      </div>
      {!dialog.allowed_actions.includes("submit") && (
        <div className="notice caution">
          <Icon name="info" />
          <span>
            {dialog.company.registry_status === "inactive"
              ? "Компания не действует по данным реестра: черновик можно просмотреть или отменить, но не отправить."
              : "Отправка этой заявки сейчас недоступна."}
          </span>
        </div>
      )}
      <Stepper
        stages={dialog.stages}
        stage={stage}
        busy={busy}
        onGo={(number) => void go(number)}
      />
      <div className="wizard-layout">
        <section className="card stage-card" aria-labelledby="stage-heading">
          <div className="eyebrow">
            Шаг {stage} из {total}
          </div>
          <h2 id="stage-heading" ref={heading} tabIndex={-1}>
            {current.title}
          </h2>
          <p className="stage-intro">{STAGE_INTRO[stage]}</p>
          {stage === total && accuracy ? (
            <ReviewStage
              dialog={dialog}
              consents={consents}
              accuracy={accuracy}
              accuracyDraft={draftOf(accuracy)}
              onAccuracy={(draft) => change(accuracy, draft)}
              busy={busy}
              submitting={submission.busy === "submit"}
              problem={stageProblem}
              onBack={() => void go(stage - 1)}
              onJump={(number) => void go(number, true)}
              onSubmit={(documents) => void submit(documents)}
              onRecalculate={() => onRecalculate(dialog.company.id)}
              onOpenApplication={onOpenApplication}
            />
          ) : (
            <form
              noValidate
              onSubmit={(event) => {
                event.preventDefault();
                void go(stage + 1);
              }}
            >
              <div className="stage-fields">
                {current.fields.map((field) => {
                  const view = shown(field);
                  return (
                    <StageField
                      key={field.name}
                      field={view.field}
                      rangeScope={view.scope}
                      draft={draftOf(field)}
                      messages={messagesFor(field)}
                      disabled={busy}
                      onChange={(draft) => change(field, draft)}
                    />
                  );
                })}
                <ProductFacts
                  product={dialog.product}
                  fields={current.fields}
                />
              </div>
              {stageProblem && (
                <div className="notice error" role="alert">
                  <Icon name="info" />
                  <span>{stageProblem.message}</span>
                </div>
              )}
              <div className="stage-actions">
                {stage > 1 && (
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() => void go(stage - 1)}
                    disabled={busy}
                  >
                    ← Назад
                  </button>
                )}
                <button
                  type="submit"
                  className="button primary"
                  disabled={busy}
                >
                  {saving ? "Сохраняем…" : "Сохранить и продолжить"}
                  <Icon />
                </button>
              </div>
            </form>
          )}
        </section>
        <DraftSummary
          application={application}
          dialog={dialog}
          cancel={
            dialog.allowed_actions.includes("cancel") && (
              <CancelAction
                application={{
                  id: dialog.application_id,
                  version: dialog.version,
                }}
                attempts={attempts}
                reload={() => refresh()}
                announce={announce}
                onUnauthorized={onUnauthorized}
              />
            )
          }
        />
      </div>
      {prompt && (
        <UnsavedFieldsDialog
          fields={prompt}
          onStay={() => settlePrompt(false)}
          onProceed={() => settlePrompt(true)}
        />
      )}
      {leavePrompt && (
        <UnsavedLeaveDialog
          message={leavePrompt}
          onStay={() => settleLeave(false)}
          onLeave={() => settleLeave(true)}
        />
      )}
    </div>
  );
}
