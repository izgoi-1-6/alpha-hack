import { ApiError } from "../../api";

/**
 * Idempotency keys for application commands: one key per user action. Repeating the same command with the same
 * body after an unknown outcome (no response, or a gateway/server failure) reuses the key, so the server replays a
 * result it may already have committed instead of acting twice; any other action gets a fresh key. The map is
 * session-scoped: the App keeps it across navigation and clears it on account change, like the company retry.
 */
export type CommandAttempts = Map<string, { key: string; body: string }>;

export function commandKey(
  attempts: CommandAttempts,
  scope: string,
  body: unknown,
) {
  const serialized = JSON.stringify(body);
  const prior = attempts.get(scope);
  if (prior?.body === serialized) return prior.key;
  const key = crypto.randomUUID();
  attempts.set(scope, { key, body: serialized });
  return key;
}

/** The server either refused (4xx: nothing was recorded) or answered; only an unknown outcome keeps the key. */
export const outcomeUnknown = (error: unknown) =>
  !(error instanceof ApiError) || error.status === 0 || error.status >= 500;

export function settleCommand(
  attempts: CommandAttempts,
  scope: string,
  key: string,
  error?: unknown,
) {
  if (attempts.get(scope)?.key !== key) return;
  if (error === undefined || !outcomeUnknown(error)) attempts.delete(scope);
}

export type CommandProblem = {
  kind:
    | "stale"
    | "duplicate"
    | "version"
    | "status"
    | "fields"
    | "network"
    | "session"
    | "other";
  message: string;
  fields: Record<string, string>;
  /** The API's error code, when the failure was an API answer, for callers that react to one code. */
  code?: string;
  activeApplicationId?: string;
};

/**
 * The words for an unknown outcome (kind "network"): no answer at all, or a server failure (5xx, e.g. a gateway
 * that lost the API), then what to do next. Both keep the command's key, so a repeat is replayed, never doubled.
 */
export function unknownOutcome(problem: CommandProblem, next: string) {
  return `${problem.code === "NETWORK_ERROR" ? "Нет связи с сервером." : "Сервер не смог выполнить запрос."} ${next}`;
}

/** Maps the API's documented command errors to what the customer or officer can do next. */
export function commandProblem(error: unknown): CommandProblem {
  const code = error instanceof ApiError ? error.code : "";
  const problem = (
    kind: CommandProblem["kind"],
    message: string,
    fields: Record<string, string> = {},
  ): CommandProblem => ({ kind, message, fields, code });
  if (!(error instanceof ApiError))
    return problem(
      "other",
      "Не удалось выполнить действие. Повторите попытку.",
    );
  if (error.status === 401) return problem("session", error.message);
  if (error.status === 0 || error.status >= 500)
    return problem("network", error.message);
  switch (error.code) {
    case "RECOMMENDATION_STALE":
    case "RECOMMENDATION_NOT_FOUND":
      return problem(
        "stale",
        "Условия продуктов изменились после расчёта. Пересчитайте оценку и выберите продукт заново.",
      );
    case "DUPLICATE_ACTIVE_APPLICATION": {
      const id = error.details?.application_id;
      return {
        ...problem("duplicate", error.message),
        activeApplicationId: typeof id === "string" ? id : undefined,
      };
    }
    case "VERSION_CONFLICT":
      return problem(
        "version",
        "Заявка изменилась в другой вкладке или окне. Мы загрузили сохранённую версию.",
      );
    // State conflicts: the screen reloads to show the current state, with the server's message.
    case "INVALID_STATUS":
    case "APPLICATION_EXPIRED":
    case "TRUSTED_SOURCE_REQUIRED":
    case "ALREADY_ASSIGNED":
    case "ASSIGNMENT_REQUIRED":
    case "INFO_REQUEST_OPEN":
    case "MANDATORY_STOP":
    case "LIMIT_NOT_COMPUTABLE":
    // The document phase: the packet or a document is no longer in the state the screen showed.
    case "DOCUMENT_ACCEPTED":
    case "DOCUMENT_NOT_CURRENT":
    case "DOCUMENT_NOT_FOUND":
    case "DOCUMENTS_INCOMPLETE":
    case "DOCUMENT_NOT_REVIEWABLE":
    case "DOCUMENTS_NOT_ACCEPTED":
    case "COLLATERAL_INSUFFICIENT":
    case "LIMIT_BELOW_MINIMUM":
      return problem("status", error.message);
    // An officer's request for an answer the client cannot give (source-owned, or a pledge of an unsecured
    // application): the server's reason stays next to the picker.
    case "FIELD_NOT_REQUESTABLE":
      return problem(
        "fields",
        "Эти сведения нельзя запросить у клиента: снимите отмеченные поля и отправьте запрос снова.",
        error.fields ?? {},
      );
    case "VALIDATION_ERROR":
    case "CORRECTION_REQUIRED":
    case "NEED_INFO":
    case "PRODUCT_NOT_SUPPORTED":
    case "ANSWER_NOT_REQUESTED":
    case "NEED_FIELDS_LOCKED":
    case "SOURCE_OWNED_FIELDS":
    case "AMOUNT_OUT_OF_BOUNDS":
    case "DOCUMENT_TYPE_NOT_ALLOWED":
    case "VERIFIED_VALUE_REQUIRED":
    case "VERIFIED_VALUE_NOT_ALLOWED":
      return problem("fields", error.message, error.fields ?? {});
    default:
      return problem("other", error.message);
  }
}
