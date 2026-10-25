import { ApplicationStatus } from "../../api";
import { CreditHistory, OfficerDecision, SourceStatus, UserRef } from "./officerApi";

/** Statuses an officer can filter the queue by; drafts never reach the queue. */
export const QUEUE_STATUSES: ApplicationStatus[] = [
  "MANUAL_REVIEW",
  "NEED_INFO",
  "WAIT_EXTERNAL",
  "PREAPPROVED",
  "DOCS_UPLOADED",
  "DOCS_REWORK",
  "APPROVED",
  "REJECTED",
  "CANCELLED",
  "EXPIRED",
];

/** The queue's assignee column: the session officer is «Я». */
export const assigneeLabel = (assignee: UserRef | null, userId: string) =>
  assignee === null
    ? "Не назначена"
    : assignee.id === userId
      ? "Я"
      : assignee.display_name;

/** A short reference for dense tables and headings; the full id stays in the address. */
export const shortId = (id: string) => id.slice(0, 8);

export const capitalize = (text: string) =>
  text.charAt(0).toUpperCase() + text.slice(1);

export const RISK_SHORT = { low: "Низкий", medium: "Средний", high: "Высокий" };
export const RISK_TONE = {
  low: "success",
  medium: "warning",
  high: "danger",
} as const;

export const SOURCE_STATUS: Record<SourceStatus, string> = {
  available: "Ответил",
  missing: "Нет данных",
  unavailable: "Недоступен",
};

export const CREDIT_HISTORY: Record<CreditHistory, string> = {
  clean: "без просрочек",
  minor_closed: "закрытые незначительные просрочки",
  serious: "серьёзные просрочки",
};

/** R5 review flags in the officer's words; the evaluation's reasons give the full server text. */
export const REVIEW_FLAGS: Record<string, string> = {
  zero_revenue: "Нулевая выручка",
  invalid_source: "Некорректные данные источника",
  declared_finance: "Финансы заявлены клиентом",
  finance_override: "Расхождение с источником",
  collateral_unconfirmed: "Залог не подтверждён или обременён",
  tax_debt: "Налоговая задолженность",
  legal_proceedings: "Судебные разбирательства",
  registry_unconfirmed: "Статус в реестре не подтверждён",
};

export const ORIGIN: Record<"source" | "override" | "declared", string> = {
  source: "Совпадает с источником",
  override: "Расхождение: исходное значение источника сохранено",
  declared: "Заявлено клиентом: в источнике нет значения",
};

export const DECISION_ACTION: Record<OfficerDecision["action"], string> = {
  preapprove: "Предварительное одобрение",
  approve: "Одобрение",
  reject: "Отказ",
  request_info: "Запрос сведений",
};
export const PHASE: Record<OfficerDecision["phase"], string> = {
  preliminary: "предварительный",
  final: "окончательный",
};

type RequestableField = { path: string; label: string };

/**
 * Answers an officer may ask the client about, by questionnaire stage: the server's `info_requests.OFFICER_PATHS`
 * (every answer outside the stage-2 need, which is fixed at submission). The pledge is requested as a whole and only
 * for the secured product. Labels are the questionnaire's own, so the client sees the same words.
 */
export const REQUESTABLE: {
  title: string;
  securedOnly?: boolean;
  fields: RequestableField[];
}[] = [
  {
    title: "Компания",
    fields: [
      {
        path: "company_confirmed",
        label: "Сведения о компании из демо-реестра верны",
      },
      { path: "actual_address", label: "Фактический адрес" },
      { path: "actual_activity", label: "Фактическая деятельность" },
    ],
  },
  {
    title: "Залог",
    securedOnly: true,
    fields: [{ path: "collateral", label: "Залог: все сведения" }],
  },
  {
    title: "Бизнес и финансы",
    fields: [
      {
        path: "monthly_revenue_rub",
        label: "Среднемесячная выручка за текущий период, ₽",
      },
      {
        path: "previous_monthly_revenue_rub",
        label: "Среднемесячная выручка за предыдущий период, ₽",
      },
      {
        path: "financial_period_end",
        label: "Дата окончания отчётного периода",
      },
      { path: "tax_regime", label: "Налоговый режим" },
      { path: "employees", label: "Число сотрудников" },
      { path: "seasonal", label: "Выручка зависит от сезона" },
    ],
  },
  {
    title: "Обязательства",
    fields: [
      {
        path: "monthly_debt_payment_rub",
        label: "Ежемесячные платежи по действующим кредитам и лизингу, ₽",
      },
      { path: "tax_debt_rub", label: "Налоговая задолженность, ₽" },
      { path: "legal_proceedings", label: "Есть судебные разбирательства" },
      { path: "obligations_note", label: "Комментарий к обязательствам" },
    ],
  },
  {
    title: "Руководитель и владельцы",
    fields: [
      {
        path: "representative_name",
        label: "ФИО представителя (синтетические данные)",
      },
      {
        path: "representative_authority_confirmed",
        label: "Подтверждение полномочий представителя",
      },
      {
        path: "beneficial_owners_confirmed",
        label: "Подтверждение сведений о владельцах",
      },
    ],
  },
  {
    title: "Проверка",
    fields: [
      {
        path: "accuracy_confirmed",
        label: "Подтверждение достоверности анкеты",
      },
    ],
  },
];

const OTHER_LABELS: Record<string, string> = {
  purpose: "Цель финансирования",
  funding_pattern: "Как используются деньги",
  requested_amount_rub: "Сумма, ₽",
  term_months: "Срок, мес.",
  collateral: "Залог",
  "collateral.status": "Залог: статус",
  "collateral.type": "Залог: тип",
  "collateral.declared_value_rub": "Залог: заявленная стоимость",
  "collateral.description": "Залог: описание",
  "collateral.owner_confirmed": "Залог: подтверждение собственности",
  "collateral.encumbered": "Залог: обременение",
};
const LABELS = new Map<string, string>([
  ...REQUESTABLE.flatMap((group) =>
    group.fields.map((field) => [field.path, field.label] as [string, string]),
  ),
  ...Object.entries(OTHER_LABELS),
]);

/** The questionnaire label of any answer path an information request may name. */
export const answerLabel = (path: string) => LABELS.get(path) ?? path;
