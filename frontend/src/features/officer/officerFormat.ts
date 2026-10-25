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

/**
 * The questionnaire's labels by answer path, in the client's own words: the server's stage descriptors, and pledge
 * details as the client's answer form names them. Unknown paths fall back to the path itself.
 */
const ANSWER_LABELS: Record<string, string> = {
  company_confirmed: "Сведения о компании из реестра верны",
  actual_address: "Фактический адрес",
  actual_activity: "Фактическая деятельность",
  purpose: "Цель финансирования",
  requested_amount_rub: "Сумма, ₽",
  term_months: "Срок, мес.",
  collateral: "Залог: все сведения",
  "collateral.status": "Залог: статус",
  "collateral.type": "Тип залога",
  "collateral.declared_value_rub": "Заявленная стоимость залога, ₽",
  "collateral.description": "Описание залога",
  "collateral.owner_confirmed": "Собственность на залог подтверждена",
  "collateral.encumbered": "Есть обременение",
  monthly_revenue_rub: "Среднемесячная выручка за текущий период, ₽",
  previous_monthly_revenue_rub: "Среднемесячная выручка за предыдущий период, ₽",
  financial_period_end: "Дата окончания отчётного периода",
  tax_regime: "Налоговый режим",
  employees: "Число сотрудников",
  seasonal: "Выручка зависит от сезона",
  monthly_debt_payment_rub:
    "Ежемесячные платежи по действующим кредитам и лизингу, ₽",
  tax_debt_rub: "Налоговая задолженность, ₽",
  legal_proceedings: "Есть судебные разбирательства",
  obligations_note: "Комментарий к обязательствам",
  representative_name: "ФИО представителя",
  representative_authority_confirmed:
    "Полномочия представителя подтверждены через Госуслуги",
  beneficial_owners_confirmed:
    "Сведения о владельцах указаны верно (это не согласие поручителя)",
  accuracy_confirmed: "Подтверждаю, что сведения анкеты верны",
};

/** The questionnaire stage each answer belongs to, as the request form groups them (the pledge on its own). */
const STAGE_OF = new Map<string, string>(
  (
    [
      ["Компания", ["company_confirmed", "actual_address", "actual_activity"]],
      ["Залог", ["collateral"]],
      [
        "Бизнес и финансы",
        [
          "monthly_revenue_rub",
          "previous_monthly_revenue_rub",
          "financial_period_end",
          "tax_regime",
          "employees",
          "seasonal",
        ],
      ],
      [
        "Обязательства",
        [
          "monthly_debt_payment_rub",
          "tax_debt_rub",
          "legal_proceedings",
          "obligations_note",
        ],
      ],
      [
        "Руководитель и владельцы",
        [
          "representative_name",
          "representative_authority_confirmed",
          "beneficial_owners_confirmed",
        ],
      ],
      ["Проверка", ["accuracy_confirmed"]],
    ] as [string, string[]][]
  ).flatMap(([title, names]) => names.map((name) => [name, title] as [string, string])),
);

/** The questionnaire label of any answer path an information request may name. */
export const answerLabel = (path: string) => ANSWER_LABELS[path] ?? path;

/**
 * The paths an officer may request, from the server's `requestable_fields` and in its order, grouped by questionnaire
 * stage; a pledge detail (`collateral.<key>`) sits with the pledge. An unknown path is offered under its own name.
 */
export function requestableGroups(paths: string[]) {
  const groups: { title: string; fields: { path: string; label: string }[] }[] = [];
  for (const path of paths) {
    const title = STAGE_OF.get(path.split(".")[0]) ?? "Другие сведения";
    let group = groups.find((entry) => entry.title === title);
    if (!group) groups.push((group = { title, fields: [] }));
    group.fields.push({ path, label: answerLabel(path) });
  }
  return groups;
}
