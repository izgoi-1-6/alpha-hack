import {
  Application,
  ApplicationDocument,
  ApplicationStatus,
  Company,
  Evaluation,
  HistoryItem,
  InfoRequest,
  Precheck,
  request,
} from "../../api";

/** Officer routes under /officer/applications (CREDIT_OFFICER only; the server refuses a client with 403). */

export type StaffAction =
  | "claim"
  | "request_info"
  | "preapprove"
  | "review_document"
  | "approve"
  | "reject";
export type UserRef = { id: string; display_name: string };
export type SourceStatus = "available" | "missing" | "unavailable";
export type CreditHistory = "clean" | "minor_closed" | "serious";

/** Points per factor as the server scored them (the total is their sum). */
export type ScoreFactors = {
  age_months: number;
  age_points: number;
  revenue_growth_points: number;
  debt_burden_points: number;
  credit_history: CreditHistory;
  credit_history_points: number;
};
export type StaffEvaluation = Evaluation & {
  factors: ScoreFactors | null;
  review_flags: string[];
};
/** A stage-3 answer beside its turnover source value; `origin` tags a conflict (override) or a declaration. */
export type FinanceEvidence = {
  answer: number | string | null;
  source: number | string | null;
  source_status: SourceStatus;
  origin: "source" | "override" | "declared" | null;
  value: number | string | null;
  submitted_answer?: number | string | null;
};
/** An immutable evaluation in full: what was scored and the evidence it used. */
export type EvaluationRecord = StaffEvaluation & {
  input_snapshot: {
    finance?: Record<string, FinanceEvidence>;
    answers?: Record<string, unknown>;
    age_months?: number;
  };
  sources: Record<string, unknown>;
};
export type StaffInfoRequest = InfoRequest & {
  officer: UserRef | null;
  /** False once resolved, and for an unresolved request of a terminal application (an audit row). */
  open: boolean;
};
export type Preapproval = {
  amount_min_rub: number | null;
  amount_max_rub: number | null;
  blocked_by: {
    code: "MANDATORY_STOP" | "LIMIT_NOT_COMPUTABLE";
    message: string;
  } | null;
};
/** DOCS_UPLOADED only: the inclusive final amount bounds from the accepted evidence, or why approval is refused. */
export type FinalApproval = {
  amount_min_rub: number | null;
  amount_max_rub: number | null;
  verified_limit_rub: number | null;
  blocked_by: {
    code:
      | "DOCUMENTS_NOT_ACCEPTED"
      | "LIMIT_NOT_COMPUTABLE"
      | "COLLATERAL_INSUFFICIENT"
      | "LIMIT_BELOW_MINIMUM";
    message: string;
  } | null;
};
export type StaffDocument = ApplicationDocument & { reviewer: UserRef | null };
export type StaffApplication = Omit<
  Application,
  "allowed_actions" | "latest_evaluation" | "open_info_request"
> & {
  assignee: UserRef | null;
  /** What the session officer may do now. */
  allowed_actions: StaffAction[];
  latest_evaluation: StaffEvaluation | null;
  open_info_request: StaffInfoRequest | null;
  /** MANUAL_REVIEW only: the inclusive amount bounds, or why preliminary approval is refused. */
  preapproval: Preapproval | null;
  final_approval: FinalApproval | null;
};
export type BkiReport = {
  evaluation_id: string;
  provider: string;
  synthetic: boolean;
  attempt: number;
  status: SourceStatus;
  credit_history: CreditHistory | null;
  current_overdue_days: number | null;
  requested_at: string;
  reused_from_evaluation_id?: string;
};
export type OfficerDecision = {
  id: string;
  officer: UserRef;
  phase: "preliminary" | "final";
  action: "preapprove" | "approve" | "reject" | "request_info";
  amount_rub: number | null;
  reason: string;
  evaluation_id: string | null;
  created_at: string;
};
export type StaffHistoryItem = HistoryItem & { actor: UserRef | null };
export type StaffDetail = {
  application: StaffApplication;
  evaluations: EvaluationRecord[];
  source_evidence: {
    company: Company & { business_reference_date: string | null };
    precheck: Precheck;
    finance: Record<string, FinanceEvidence>;
    bki: BkiReport[];
  };
  decisions: OfficerDecision[];
  info_requests: StaffInfoRequest[];
  history: StaffHistoryItem[];
  /** Every revision, in checklist order, then revision. */
  documents: StaffDocument[];
  /** Answer paths an officer may request for this product (pledge paths only for the secured product). */
  requestable_fields: string[];
};

export type AssigneeFilter = "me" | "unassigned";
export type QueueFilters = {
  status?: ApplicationStatus;
  assignee?: AssigneeFilter;
};

type StaffBody = { application: StaffApplication };
const officerPath = (id: string) =>
  "/officer/applications/" + encodeURIComponent(id);
const command =
  <B>(action: string) =>
  (id: string, body: B, key: string) =>
    request<StaffBody>(`${officerPath(id)}/${action}`, {
      method: "POST",
      body,
      idempotencyKey: key,
    });

export const officerApi = {
  /** Submitted applications, oldest submission first; DRAFT is excluded unless asked for. */
  queue: (filters: QueueFilters, signal?: AbortSignal) => {
    const query = new URLSearchParams();
    if (filters.status) query.set("status", filters.status);
    if (filters.assignee) query.set("assignee", filters.assignee);
    const suffix = query.toString() ? "?" + query.toString() : "";
    return request<{ items: StaffApplication[]; total: number }>(
      "/officer/applications" + suffix,
      { signal },
    );
  },
  detail: (id: string, signal?: AbortSignal) =>
    request<StaffDetail>(officerPath(id), { signal }),
  claim: command<{ version: number }>("claim"),
  requestInfo: command<{
    version: number;
    reason: string;
    requested_fields: string[];
  }>("request-info"),
  preapprove: command<{ version: number; amount_rub: number; reason: string }>(
    "preapprove",
  ),
  reject: command<{ version: number; reason: string }>("reject"),
};
