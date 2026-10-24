export type User = {
  id: string;
  email: string;
  display_name: string;
  role: "CLIENT" | "CREDIT_OFFICER";
};
export type Company = {
  id: string;
  inn: string;
  entity_type: "IP" | "LLC";
  name: string | null;
  registry_status: "active" | "inactive" | "unknown";
  registered_at: string | null;
  okved: string | null;
  region: string | null;
  legal_address: string | null;
  fixture_id: string | null;
  version: number;
  created_at: string;
  updated_at: string;
};
export type Precheck = {
  id: string;
  registry_source_status: "available" | "missing" | "unavailable";
  turnover_source_status: "available" | "missing" | "unavailable";
  monthly_revenue_rub: number | null;
  previous_monthly_revenue_rub: number | null;
  financial_period_end: string | null;
  source_version: string;
  checked_at: string;
  synthetic: true;
};
export type CompanyResult = { company: Company; precheck: Precheck };
export type Fixture = {
  fixture_id: string;
  inn: string;
  name: string;
  entity_type: "IP" | "LLC";
  registry_status: string;
  registry_source_status: string;
  turnover_source_status: string;
};
export type ConsentDocument = { code: string; version: string; text: string };
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fields: Record<string, string> = {},
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}
export async function request<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    idempotencyKey?: string;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/api/v1" + path, {
      method: options.method ?? "GET",
      credentials: "same-origin",
      signal: options.signal,
      headers: {
        ...(options.body !== undefined
          ? { "Content-Type": "application/json" }
          : {}),
        ...(options.idempotencyKey
          ? { "Idempotency-Key": options.idempotencyKey }
          : {}),
      },
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(
      0,
      "NETWORK_ERROR",
      "Нет связи с сервером. Проверьте подключение и повторите попытку.",
    );
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      data?.error?.code ?? "HTTP_ERROR",
      data?.error?.message ?? "Не удалось выполнить запрос. Повторите попытку.",
      data?.error?.fields,
      data?.error?.details,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export const api = {
  me: () => request<{ user: User }>("/auth/me"),
  login: (email: string, password: string) =>
    request<{ user: User }>("/auth/login", {
      method: "POST",
      body: { email, password },
    }),
  register: (email: string, password: string, display_name: string) =>
    request<{ user: User }>("/auth/register", {
      method: "POST",
      body: { email, password, display_name },
    }),
  logout: () => request<void>("/auth/logout", { method: "POST", body: {} }),
  companies: () => request<{ items: Company[]; total: number }>("/companies"),
  company: (id: string) => request<CompanyResult>("/companies/" + id),
  fixtures: () =>
    request<{ items: Fixture[]; total: number }>("/demo/fixtures"),
  consents: () =>
    request<{ items: ConsentDocument[] }>(
      "/consents/documents?stage=onboarding",
    ),
  onboard: (inn: string, consents: ConsentDocument[]) =>
    request<CompanyResult>("/companies", {
      method: "POST",
      body: {
        inn,
        consents: consents.map(({ code, version }) => ({
          code,
          version,
          accepted: true,
        })),
      },
    }),
  retry: (id: string, version: number, key: string) =>
    request<CompanyResult>(`/companies/${id}/precheck/retry`, {
      method: "POST",
      body: { version },
      idempotencyKey: key,
    }),
};

export const errorMessage = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Не удалось выполнить действие. Повторите попытку.";
