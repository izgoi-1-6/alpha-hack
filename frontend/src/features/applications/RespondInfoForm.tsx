import { FormEvent, useState } from "react";
import {
  AnswerValue,
  Answers,
  Application,
  applicationsApi,
  Dialog,
  FieldDescriptor,
  InfoRequest,
} from "../../api";
import { Icon } from "../../components";
import { CommandAttempts, unknownOutcome } from "./commands";
import {
  answerAt,
  answerPaths,
  FieldDraft,
  fromDraft,
  toDraft,
} from "./fields";
import { idOf, StageField } from "./StageFields";
import { useCommand } from "./useCommand";

const PLEDGE_DETAILS: Record<
  string,
  (pledge: FieldDescriptor) => Omit<FieldDescriptor, "name" | "required">
> = {
  status: (pledge) => ({
    label: "Залог: статус",
    type: "enum",
    options: pledge.statuses,
  }),
  type: (pledge) => ({ label: "Тип залога", type: "enum", options: pledge.types }),
  declared_value_rub: () => ({
    label: "Заявленная стоимость залога, ₽",
    type: "integer",
  }),
  description: (pledge) => ({
    label: "Описание залога",
    type: "text",
    max_length: pledge.description_max_length ?? 500,
  }),
  owner_confirmed: () => ({
    label: "Собственность на залог подтверждена",
    type: "boolean",
  }),
  encumbered: () => ({ label: "Есть обременение", type: "boolean" }),
};

/**
 * The questionnaire widgets for exactly the requested paths: a whole answer, or a single pledge detail
 * (`collateral.<key>`, unless the whole pledge is requested too). Descriptors come from the server's dialog.
 */
function requestedFields(dialog: Dialog, paths: string[]): FieldDescriptor[] {
  const byName = new Map(
    dialog.stages.flatMap((stage) => stage.fields).map((field) => [field.name, field]),
  );
  const fields: FieldDescriptor[] = [];
  for (const path of paths) {
    const [name, key] = path.split(".");
    const field = byName.get(name);
    if (!key) {
      if (field) fields.push(field);
    } else if (field && !paths.includes(name) && PLEDGE_DETAILS[key])
      fields.push({ ...PLEDGE_DETAILS[key](field), name: path, required: true });
  }
  return fields;
}

/** Puts a parsed value at its answer path; pledge details are merged into one partial `collateral` object. */
function setAnswer(answers: Answers, path: string, value: AnswerValue) {
  const [name, key] = path.split(".");
  if (!key) answers[name] = value;
  else
    answers[name] = {
      ...((answers[name] as Record<string, AnswerValue> | undefined) ?? {}),
      [key]: value,
    };
}

/**
 * The client's answer to an open client_answers request: the requested fields prefilled with the saved answers, and
 * a response for the officer. Sent once per key; a refused or stale attempt keeps what the client typed.
 */
export function RespondInfoForm({
  application,
  request,
  dialog,
  attempts,
  reload,
  announce,
  onResponded,
  onUnauthorized,
}: {
  application: Application;
  request: InfoRequest;
  dialog: Dialog;
  attempts: CommandAttempts;
  reload: () => Promise<unknown>;
  announce: (text: string) => void;
  onResponded: () => void;
  onUnauthorized: () => void;
}) {
  const command = useCommand(attempts, onUnauthorized);
  const [fields] = useState(() =>
    requestedFields(dialog, request.requested_fields),
  );
  const [drafts, setDrafts] = useState<Record<string, FieldDraft>>(() =>
    Object.fromEntries(
      fields.map((field) => [
        field.name,
        toDraft(field, answerAt(application.answers, field.name)),
      ]),
    ),
  );
  const [response, setResponse] = useState("");
  const [messages, setMessages] = useState<Record<string, string>>({});
  const busy = !!command.busy;
  const headingId = `respond-${request.id}`;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const answers: Answers = {};
    const errors: Record<string, string> = {};
    for (const field of fields) {
      const parsed = fromDraft(field, drafts[field.name]);
      Object.assign(errors, parsed.errors);
      setAnswer(answers, field.name, parsed.value);
    }
    setMessages(errors);
    if (Object.keys(errors).length) {
      document.getElementById(idOf(Object.keys(errors)[0]))?.focus();
      return;
    }
    const body = {
      version: application.version,
      response: response.trim(),
      answers,
    };
    const result = await command.run(
      "respond",
      `respond:${application.id}`,
      body,
      (key) => applicationsApi.respondInfo(application.id, body, key),
    );
    if (!result) return;
    if (result.ok) {
      announce("Ответ отправлен. Заявка снова на рассмотрении у специалиста.");
      await reload();
      onResponded();
    } else if (result.problem.kind === "fields")
      setMessages(answerPaths(result.problem.fields));
    else if (["version", "status"].includes(result.problem.kind)) await reload();
  }

  return (
    <form
      className="respond-form"
      aria-labelledby={headingId}
      onSubmit={(event) => void submit(event)}
      noValidate
    >
      <h3 id={headingId}>Ответ на запрос</h3>
      <p className="field-note">
        Измените только запрошенные сведения: остальные ответы анкеты и сумма
        заявки остаются прежними.
      </p>
      <div className="stage-fields">
        {fields.map((field) => (
          <StageField
            key={field.name}
            field={field}
            draft={drafts[field.name]}
            messages={messages}
            disabled={busy}
            onChange={(draft) =>
              setDrafts((current) => ({ ...current, [field.name]: draft }))
            }
          />
        ))}
        <div className="field">
          <label htmlFor={idOf("response")}>Ответ специалисту</label>
          <textarea
            id={idOf("response")}
            rows={3}
            maxLength={2000}
            value={response}
            disabled={busy}
            aria-invalid={messages.response ? true : undefined}
            aria-describedby={
              idOf("response") +
              "-hint" +
              (messages.response ? ` ${idOf("response")}-error` : "")
            }
            onChange={(event) => setResponse(event.target.value)}
          />
          <p className="field-note" id={idOf("response") + "-hint"}>
            Коротко поясните ответ: специалист увидит его в заявке. До 2000
            символов.
          </p>
          {messages.response && (
            <p className="field-error" id={idOf("response") + "-error"}>
              {messages.response}
            </p>
          )}
        </div>
      </div>
      {command.problem && (
        <div className="notice error" role="alert">
          <Icon name="info" />
          <span>
            {command.problem.kind === "network"
              ? unknownOutcome(
                  command.problem,
                  "Ответ мог уже сохраниться: отправьте ещё раз — повтор не создаст второй ответ.",
                )
              : command.problem.message}
          </span>
        </div>
      )}
      <button
        type="submit"
        className="button primary"
        disabled={busy || !response.trim()}
      >
        {busy ? "Отправляем…" : "Отправить ответ"}
      </button>
    </form>
  );
}
