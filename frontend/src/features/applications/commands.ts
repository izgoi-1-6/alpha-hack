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
  activeApplicationId?: string;
};

/** Maps the API's documented command errors to what the customer can do next. */
export function commandProblem(error: unknown): CommandProblem {
  const problem = (
    kind: CommandProblem["kind"],
    message: string,
    fields: Record<string, string> = {},
  ): CommandProblem => ({ kind, message, fields });
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
    case "INVALID_STATUS":
    case "APPLICATION_EXPIRED":
      return problem("status", error.message);
    case "VALIDATION_ERROR":
    case "CORRECTION_REQUIRED":
    case "NEED_INFO":
    case "PRODUCT_NOT_SUPPORTED":
      return problem("fields", error.message, error.fields ?? {});
    default:
      return problem("other", error.message);
  }
}
