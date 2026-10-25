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
    throw networkError();
  }
  if (!response.ok)
    throw responseError(
      response.status,
      await response.json().catch(() => null),
    );
  return response.status === 204 ? (undefined as T) : response.json();
}
/** No response at all: the outcome of a command is unknown. */
export const networkError = () =>
  new ApiError(
    0,
    "NETWORK_ERROR",
    "Нет связи с сервером. Проверьте подключение и повторите попытку.",
  );
/** An API refusal `{error:{code,message,fields?,details?}}`, or a generic one when the body is not that shape. */
export function responseError(status: number, data: unknown) {
  const error = (data as { error?: Partial<ApiError> } | null)?.error;
  return new ApiError(
    status,
    error?.code ?? "HTTP_ERROR",
    error?.message ?? "Не удалось выполнить запрос. Повторите попытку.",
    error?.fields,
    error?.details,
  );
}
export const api = {
  me: (signal?: AbortSignal) => request<{ user: User }>("/auth/me", { signal }),
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
  companies: (signal?: AbortSignal) =>
    request<{ items: Company[]; total: number }>("/companies", { signal }),
  company: (id: string, signal?: AbortSignal) =>
    request<CompanyResult>("/companies/" + id, { signal }),
  fixtures: (signal?: AbortSignal) =>
    request<{ items: Fixture[]; total: number }>("/demo/fixtures", { signal }),
  consents: (signal?: AbortSignal) =>
    request<{ items: ConsentDocument[] }>(
      "/consents/documents?stage=onboarding",
      { signal },
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

export type Need = {
  purpose:
    | "working_capital"
    | "business_development"
    | "investment"
    | "refinancing";
  funding_pattern: "one_time" | "repeated";
  requested_amount_rub: number;
  term_months: number;
  collateral: {
    status: "unknown" | "none" | "declared";
    type?: "real_estate" | "vehicle" | "equipment" | "inventory" | "deposit";
    declared_value_rub?: number;
    description?: string;
    owner_confirmed?: boolean;
    encumbered?: boolean;
  } | null;
};
export type Product = {
  id: string;
  name: string;
  instrument_type: string;
  purposes: string[];
  amount_min_rub: number;
  amount_max_rub: number;
  term_min_months: number;
  term_max_months: number;
  annual_rate_bps: number;
  collateral_required: boolean;
  collateral_ltv_bps: number | null;
  can_apply: boolean;
};
export type Catalog = {
  catalog_version: string;
  rules_version: string;
  notice: string;
  products: Product[];
  research_items: { id: string; name: string; can_apply: false }[];
};
export type Recommendation = {
  product_id: string;
  rank: number;
  status: "fits" | "needs_info" | "does_not_fit";
  can_apply: boolean;
  indicative_limit_rub: number | null;
  catalog_max_rub: number;
  requested_amount_rub: number;
  checks: {
    code: string;
    result: "passed" | "failed" | "unknown";
    text: string;
  }[];
  reasons: string[];
  alternatives: string[];
  estimated_payment_rub: number | null;
  payment_note: string;
};
export type RecommendationSnapshot = {
  snapshot_id: string;
  catalog_version: string;
  rules_version: string;
  items: Recommendation[];
  created_at: string;
};
export const recommendationsApi = {
  catalog: (signal?: AbortSignal) => request<Catalog>("/catalog", { signal }),
  calculate: (companyId: string, need: Need, signal?: AbortSignal) =>
    request<RecommendationSnapshot>(`/companies/${companyId}/recommendations`, {
      method: "POST",
      body: need,
      signal,
    }),
  snapshot: (companyId: string, snapshotId: string, signal?: AbortSignal) =>
    request<RecommendationSnapshot>(
      `/companies/${companyId}/recommendations/${snapshotId}`,
      { signal },
    ),
};

export type ApplicationStatus =
  | "DRAFT"
  | "CHECKING"
  | "WAIT_EXTERNAL"
  | "MANUAL_REVIEW"
  | "NEED_INFO"
  | "PREAPPROVED"
  | "DOCS_UPLOADED"
  | "DOCS_REWORK"
  | "APPROVED"
  | "REJECTED"
  | "CANCELLED"
  | "EXPIRED";
export type ApplicationAction =
  | "edit_answers"
  | "submit"
  | "retry_check"
  | "respond_info"
  | "upload_document"
  | "delete_document"
  | "complete_documents"
  | "cancel";
export type DocumentType =
  | "BANK_STATEMENT"
  | "FINANCIAL_REPORT"
  | "COLLATERAL_OWNERSHIP"
  | "COLLATERAL_VALUATION";
export type DocumentStatus =
  | "UPLOADED"
  | "ACCEPTED"
  | "REJECTED"
  | "SUPERSEDED"
  | "DELETED";
/** One stored revision (never the storage key or the reviewer's identity). `download_url` is null once deleted. */
export type ApplicationDocument = {
  id: string;
  application_id: string;
  document_type: DocumentType;
  revision: number;
  original_name: string;
  media_type: "application/pdf" | "image/jpeg" | "image/png";
  size_bytes: number;
  sha256: string;
  status: DocumentStatus;
  review_reason: string | null;
  verified_value_rub: number | null;
  created_at: string;
  reviewed_at: string | null;
  download_url: string | null;
};
/** `current_uploaded` counts requirements with a current document whatever its review. Null before preapproval. */
export type DocumentSummary = {
  required_total: number;
  current_uploaded: number;
  accepted: number;
  rejected: number;
  missing: DocumentType[];
  can_complete: boolean;
};
export type DocumentChecklist = {
  /** «Демонстрационная проверка документов…»: the review label the UI shows (no antivirus or authenticity claim). */
  notice: string;
  requirements: {
    document_type: DocumentType;
    required: boolean;
    current_document: ApplicationDocument | null;
  }[];
  items: ApplicationDocument[];
};
/** A saved pledge answer: keys are merged on each save and may be null (cleared or not yet given). */
export type Collateral = {
  status?: "unknown" | "none" | "declared" | null;
  type?: NonNullable<Need["collateral"]>["type"] | null;
  declared_value_rub?: number | null;
  description?: string | null;
  owner_confirmed?: boolean | null;
  encumbered?: boolean | null;
};
export type AnswerValue = string | number | boolean | Collateral | null;
export type Answers = Record<string, AnswerValue>;
export type ApplicationCompany = Pick<
  Company,
  "id" | "name" | "inn" | "entity_type" | "registry_status"
>;
/** The policy pinned at submission, or the live one for a draft (only `id` if it was withdrawn). */
export type ApplicationProduct = { id: string } & Partial<{
  name: string;
  instrument_type: string;
  amount_min_rub: number;
  amount_max_rub: number;
  term_min_months: number;
  term_max_months: number;
  annual_rate_bps: number;
  rate_is_demo: boolean;
  collateral_required: boolean;
  collateral_ltv_bps: number | null;
  required_documents: string[];
}>;
export type Evaluation = {
  id: string;
  rule: string;
  outcome: ApplicationStatus;
  score: number | null;
  risk: "low" | "medium" | "high" | null;
  scored_limit_rub: number | null;
  reasons: string[];
  created_at: string;
};
export type InfoRequest = {
  id: string;
  kind: "client_answers" | "trusted_source";
  source: "registry" | "turnover" | "bki" | null;
  requested_fields: string[];
  question: string;
  requested_by: "system" | "officer";
  response: string | null;
  responded_at: string | null;
  resolved_at: string | null;
  created_at: string;
};
export type Application = {
  id: string;
  company_id: string;
  product_id: string;
  recommendation_snapshot_id: string;
  status: ApplicationStatus;
  current_stage: number;
  version: number;
  answers: Answers;
  submitted_at: string | null;
  requested_amount_rub: number | null;
  indicative_limit_rub: number | null;
  scored_limit_rub: number | null;
  preapproved_amount_rub: number | null;
  final_amount_rub: number | null;
  preapproved_at: string | null;
  preapproval_expires_at: string | null;
  catalog_version: string;
  rules_version: string;
  created_at: string;
  updated_at: string;
  company: ApplicationCompany;
  product: ApplicationProduct;
  latest_evaluation: Evaluation | null;
  allowed_actions: ApplicationAction[];
  missing_fields: string[];
  open_info_request: InfoRequest | null;
  document_summary: DocumentSummary | null;
};
export type FieldOption = { value: string; label: string };
export type FieldDescriptor = {
  name: string;
  label: string;
  type: "boolean" | "text" | "enum" | "integer" | "date" | "collateral";
  required: boolean;
  must_be_true?: boolean;
  max_length?: number;
  min?: number;
  max?: number;
  options?: FieldOption[];
  statuses?: FieldOption[];
  types?: FieldOption[];
  description_max_length?: number;
  source?: {
    name: "turnover";
    status: "available" | "missing" | "unavailable";
    value: number | string | null;
  };
  origin?: "source" | "override" | "declared" | null;
};
export type DialogStage = {
  number: number;
  title: string;
  fields: FieldDescriptor[];
  complete: boolean;
};
export type Dialog = {
  application_id: string;
  status: ApplicationStatus;
  version: number;
  current_stage: number;
  steps_total: number;
  company: ApplicationCompany;
  product: ApplicationProduct;
  stages: DialogStage[];
  answers: Answers;
  missing_fields: string[];
  field_issues: Record<string, string>;
  allowed_actions: ApplicationAction[];
};
export type HistoryItem = {
  id: string;
  application_id: string;
  from_status: ApplicationStatus | null;
  to_status: ApplicationStatus;
  /** Who made the change; the customer's history never names users. */
  actor_role: "client" | "officer" | "system";
  reason_code: string;
  reason_text: string;
  application_version: number;
  created_at: string;
  notification: {
    event_code: string;
    channel: "demo_in_app";
    message: string;
    simulated: true;
    created_at: string;
  } | null;
};
export type SubmissionConsent = {
  code: string;
  version: string;
  accepted: true;
};
type ApplicationBody = { application: Application };
const applicationPath = (id: string) =>
  "/applications/" + encodeURIComponent(id);
export const applicationsApi = {
  list: (signal?: AbortSignal) =>
    request<{ items: Application[]; total: number }>("/applications", {
      signal,
    }),
  get: (id: string, signal?: AbortSignal) =>
    request<ApplicationBody>(applicationPath(id), { signal }),
  dialog: (id: string, signal?: AbortSignal) =>
    request<Dialog>(applicationPath(id) + "/dialog", { signal }),
  history: (id: string, signal?: AbortSignal) =>
    request<{ items: HistoryItem[]; total: number }>(
      applicationPath(id) + "/history",
      { signal },
    ),
  consents: (signal?: AbortSignal) =>
    request<{ items: ConsentDocument[] }>(
      "/consents/documents?stage=application",
      { signal },
    ),
  create: (
    body: {
      company_id: string;
      product_id: string;
      recommendation_snapshot_id: string;
    },
    key: string,
  ) =>
    request<ApplicationBody>("/applications", {
      method: "POST",
      body,
      idempotencyKey: key,
    }),
  saveAnswers: (
    id: string,
    body: { version: number; current_stage: number; answers: Answers },
  ) =>
    request<ApplicationBody>(applicationPath(id) + "/answers", {
      method: "PATCH",
      body,
    }),
  submit: (
    id: string,
    body: { version: number; consents: SubmissionConsent[] },
    key: string,
  ) =>
    request<ApplicationBody>(applicationPath(id) + "/submit", {
      method: "POST",
      body,
      idempotencyKey: key,
    }),
  retryCheck: (id: string, body: { version: number }, key: string) =>
    request<ApplicationBody>(applicationPath(id) + "/retry-check", {
      method: "POST",
      body,
      idempotencyKey: key,
    }),
  cancel: (
    id: string,
    body: { version: number; reason: string },
    key: string,
  ) =>
    request<ApplicationBody>(applicationPath(id) + "/cancel", {
      method: "POST",
      body,
      idempotencyKey: key,
    }),
  /** Answers an open client_answers request: exactly its requested paths plus a response for the officer. */
  respondInfo: (
    id: string,
    body: { version: number; response: string; answers: Answers },
    key: string,
  ) =>
    request<ApplicationBody>(applicationPath(id) + "/respond-info", {
      method: "POST",
      body,
      idempotencyKey: key,
    }),
};
