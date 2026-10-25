import { useRef, useState } from "react";
import { Icon } from "../../components";
import { CommandAttempts, CommandProblem } from "../applications/commands";
import { rub, STATUS } from "../applications/format";
import { useCommand } from "../applications/useCommand";
import { PreapproveForm, RejectForm, RequestInfoForm } from "./DecisionForms";
import { officerApi, StaffApplication } from "./officerApi";

type Decision = "preapprove" | "request_info" | "reject";
const CHOICES: { action: Decision; label: string }[] = [
  { action: "preapprove", label: "Одобрение" },
  { action: "request_info", label: "Запрос сведений" },
  { action: "reject", label: "Отказ" },
];
const TERMINAL = ["APPROVED", "REJECTED", "CANCELLED", "EXPIRED"];

function problemText(problem: CommandProblem) {
  switch (problem.kind) {
    case "network":
      return "Нет связи с сервером. Команда могла уже выполниться: повторите её — повтор с тем же ключом не создаст второе решение.";
    case "version":
      return "Заявка изменилась после загрузки страницы: мы показали актуальную версию. Введённые данные сохранены — проверьте их и отправьте снова.";
    default:
      return problem.message;
  }
}

/** Why there is nothing to do right now, when the server offers no action to this officer. */
function idleNote(application: StaffApplication, mine: boolean) {
  if (TERMINAL.includes(application.status))
    return "Заявка закрыта: решений по ней больше не принимается.";
  if (application.assignee && !mine)
    return `Заявку ведёт ${application.assignee.display_name}: решения принимает ответственный специалист.`;
  if (application.status === "NEED_INFO")
    return "Ждём ответа клиента на запрос сведений: после ответа заявка вернётся на рассмотрение.";
  if (application.status === "WAIT_EXTERNAL" || application.status === "CHECKING")
    return "Заявка ждёт ответа демо-источника: решение специалиста пока не требуется.";
  return "Сейчас по заявке нет действий для специалиста.";
}

/**
 * Claim and the preliminary decisions, offered only as the server's staff `allowed_actions` say. One command runs at
 * a time; its result is announced, and the page reloads. The forms stay mounted across a reload, so a version
 * conflict keeps what the officer typed; a lost response keeps the idempotency key for the repeat.
 */
export function DecisionPanel({
  application,
  userId,
  attempts,
  reload,
  announce,
  onDecided,
  onUnauthorized,
}: {
  application: StaffApplication;
  userId: string;
  attempts: CommandAttempts;
  reload: () => Promise<unknown>;
  announce: (text: string) => void;
  /** Runs after a decision that changed the status has been reloaded. */
  onDecided: () => void;
  onUnauthorized: () => void;
}) {
  const command = useCommand(attempts, onUnauthorized);
  const [picked, setPicked] = useState<Decision | null>(null);
  const [lastCommand, setLastCommand] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const allowed = application.allowed_actions;
  const choices = CHOICES.filter((choice) => allowed.includes(choice.action));
  const active =
    choices.find((choice) => choice.action === picked)?.action ??
    choices[0]?.action;
  const mine = application.assignee?.id === userId;
  const busy = !!command.busy;
  const blocked = application.preapproval?.blocked_by;
  const fieldsOf = (name: string) =>
    command.problem && lastCommand === name ? command.problem.fields : {};

  async function run<B>(
    name: string,
    body: B,
    send: (key: string) => Promise<{ application: StaffApplication }>,
    success: (next: StaffApplication) => string,
  ) {
    setLastCommand(name);
    const result = await command.run(
      name,
      `officer-${name}:${application.id}`,
      body,
      send,
    );
    if (!result) return;
    if (result.ok) {
      announce(success(result.value.application));
      await reload();
      if (name === "claim") heading.current?.focus();
      else onDecided();
    } else if (["version", "status"].includes(result.problem.kind))
      await reload();
  }
  const version = application.version;
  const claim = () =>
    run(
      "claim",
      { version },
      (key) => officerApi.claim(application.id, { version }, key),
      () => "Заявка взята в работу.",
    );

  return (
    <section className="card decision-card" aria-labelledby="decision-heading">
      <div className="panel-title">
        <h2 id="decision-heading" ref={heading} tabIndex={-1}>
          Решение по заявке
        </h2>
      </div>
      <p className="assignment">
        Ответственный:{" "}
        <b>
          {application.assignee
            ? mine
              ? "Я"
              : application.assignee.display_name
            : "не назначен"}
        </b>
      </p>
      {allowed.includes("claim") && (
        <div className="claim-row">
          <p className="field-note">
            Решения принимает специалист, который взял заявку в работу.
          </p>
          <button
            type="button"
            className="button primary"
            disabled={busy}
            onClick={() => void claim()}
          >
            {command.busy === "claim" ? "Берём в работу…" : "Взять в работу"}
          </button>
        </div>
      )}
      {mine && blocked && (
        <div className="notice caution">
          <Icon name="info" />
          <span>{blocked.message}</span>
        </div>
      )}
      {choices.length === 0 && !allowed.includes("claim") && (
        <p className="muted">{idleNote(application, mine)}</p>
      )}
      {choices.length > 1 && (
        <div className="decision-choices" role="group" aria-label="Действие">
          {choices.map((choice) => (
            <button
              key={choice.action}
              type="button"
              className={active === choice.action ? "chosen" : undefined}
              aria-pressed={active === choice.action}
              aria-controls={`decision-${choice.action}`}
              onClick={() => setPicked(choice.action)}
            >
              {choice.label}
            </button>
          ))}
        </div>
      )}
      {allowed.includes("preapprove") && application.preapproval && (
        <div id="decision-preapprove" hidden={active !== "preapprove"}>
          <PreapproveForm
            preapproval={application.preapproval}
            busy={busy}
            fields={fieldsOf("preapprove")}
            onSubmit={(amount, reason) => {
              const body = { version, amount_rub: amount, reason };
              void run(
                "preapprove",
                body,
                (key) => officerApi.preapprove(application.id, body, key),
                (next) =>
                  `Заявка предварительно одобрена на ${rub(next.preapproved_amount_rub ?? amount)}.`,
              );
            }}
          />
        </div>
      )}
      {allowed.includes("request_info") && (
        <div id="decision-request_info" hidden={active !== "request_info"}>
          <RequestInfoForm
            secured={!!application.product.collateral_required}
            busy={busy}
            fields={fieldsOf("request-info")}
            onSubmit={(paths, question) => {
              const body = { version, reason: question, requested_fields: paths };
              void run(
                "request-info",
                body,
                (key) => officerApi.requestInfo(application.id, body, key),
                (next) =>
                  `Запрос сведений отправлен клиенту. Статус: ${STATUS[next.status].label}.`,
              );
            }}
          />
        </div>
      )}
      {allowed.includes("reject") && (
        <div id="decision-reject" hidden={active !== "reject"}>
          <RejectForm
            status={application.status}
            busy={busy}
            fields={fieldsOf("reject")}
            onSubmit={(reason) => {
              const body = { version, reason };
              void run(
                "reject",
                body,
                (key) => officerApi.reject(application.id, body, key),
                (next) => `Отказ оформлен. Статус: ${STATUS[next.status].label}.`,
              );
            }}
          />
        </div>
      )}
      {command.problem && (
        <div className="notice error" role="alert">
          <Icon name="info" />
          <span>
            {problemText(command.problem)}
            {command.problem.code === "ASSIGNMENT_REQUIRED" &&
              allowed.includes("claim") &&
              " Возьмите заявку в работу кнопкой выше."}
          </span>
        </div>
      )}
    </section>
  );
}
