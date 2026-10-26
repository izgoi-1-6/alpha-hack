import { Application } from "../../api";
import { Icon } from "../../components";
import { CommandAttempts, unknownOutcome } from "../applications/commands";
import { useCommand } from "../applications/useCommand";
import { documentsApi } from "./documentsApi";

/** The only address the link may open: the stand's own hand-off page for this application. */
export const HANDOFF_PATH = /^\/alfa-business\/([^/?#]+)$/;

/** The application id of a hand-off page address, or null for any other path (a malformed escape stays as typed). */
export function handoffIdOf(pathname: string) {
  const match = HANDOFF_PATH.exec(pathname);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

/**
 * «Перейти в Альфа-Бизнес» for an APPROVED application: asks the server for the link, then opens the local hand-off
 * page. Nothing is sent to a bank: no redirect, no signing, no disbursement.
 */
export function HandoffAction({
  application,
  attempts,
  onOpen,
  onUnauthorized,
}: {
  application: Pick<Application, "id">;
  attempts: CommandAttempts;
  onOpen: (path: string) => void;
  onUnauthorized: () => void;
}) {
  const command = useCommand(attempts, onUnauthorized);

  async function open() {
    const body = { application_id: application.id };
    const result = await command.run(
      "handoff",
      `handoff:${application.id}`,
      body,
      (key) => documentsApi.handoffLink(body, key),
    );
    if (!result?.ok) return;
    if (HANDOFF_PATH.test(result.value.url)) onOpen(result.value.url);
    else
      command.setProblem({
        kind: "other",
        message: "Сервер вернул неожиданный адрес перехода: страница не открыта.",
        fields: {},
      });
  }

  return (
    <div className="handoff-action">
      <button
        type="button"
        className="button primary"
        disabled={!!command.busy}
        onClick={() => void open()}
      >
        {command.busy ? "Открываем…" : "Перейти в Альфа-Бизнес"}
        <Icon />
      </button>
      <p className="field-note">
        Откроется страница перехода в Альфа-Бизнес: в «Кредитном маршруте»
        договор не подписывается и деньги не перечисляются.
      </p>
      {command.problem && (
        <div className="notice error" role="alert">
          <Icon name="info" />
          <span>
            {command.problem.kind === "network"
              ? unknownOutcome(command.problem, "Повторите попытку.")
              : command.problem.message}
          </span>
        </div>
      )}
    </div>
  );
}
