import {
  Answers,
  AnswerValue,
  Collateral,
  DialogStage,
  FieldDescriptor,
} from "../../api";
import { rub } from "./format";

/** What an input holds while the customer edits it; converted to an answer value only when the stage is saved. */
export type CollateralDraft = {
  status: string | null;
  type: string | null;
  declared_value_rub: string;
  description: string;
  owner_confirmed: boolean | null;
  encumbered: boolean | null;
};
export type FieldDraft = string | boolean | null | CollateralDraft;
type Parsed = { value: AnswerValue; errors: Record<string, string> };

/** The saved answer at an answer path: a whole answer, or one pledge detail (`collateral.<key>`). */
export function answerAt(
  answers: Answers,
  path: string,
): AnswerValue | undefined {
  const [name, key] = path.split(".");
  const value = answers[name];
  if (!key) return value;
  return value && typeof value === "object"
    ? (value as Record<string, AnswerValue>)[key]
    : undefined;
}

export const isMoney = (field: FieldDescriptor) => field.name.endsWith("_rub");

/** Date-only answers are calendar dates: format them without a time-zone shift. */
export const formatDay = (value: string) =>
  new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value + "T00:00:00Z"));

export function toDraft(
  field: FieldDescriptor,
  value: AnswerValue | undefined,
): FieldDraft {
  switch (field.type) {
    case "integer":
      return typeof value === "number" ? String(value) : "";
    case "text":
    case "date":
      return typeof value === "string" ? value : "";
    case "boolean":
      return typeof value === "boolean" ? value : null;
    case "enum":
      return typeof value === "string" ? value : null;
    case "collateral": {
      const saved: Partial<Collateral> =
        value && typeof value === "object" ? value : {};
      return {
        status: saved.status ?? null,
        type: saved.type ?? null,
        declared_value_rub:
          saved.declared_value_rub != null
            ? String(saved.declared_value_rub)
            : "",
        description: saved.description ?? "",
        owner_confirmed: saved.owner_confirmed ?? null,
        encumbered: saved.encumbered ?? null,
      };
    }
  }
}

/** Whole rubles or counts typed by the customer; spaces between digit groups are accepted. */
export function parseInteger(text: string): {
  value: number | null;
  error?: string;
} {
  const digits = text.replace(/[\s ]/g, "");
  if (!digits) return { value: null };
  if (!/^\d+$/.test(digits))
    return {
      value: null,
      error: "Введите целое число: без минуса, точек и копеек",
    };
  const value = Number(digits);
  if (!Number.isSafeInteger(value))
    return { value: null, error: "Слишком большое число" };
  return { value };
}

/** Converts a draft into the answer the API stores; type errors are reported per answer path. */
export function fromDraft(field: FieldDescriptor, draft: FieldDraft): Parsed {
  if (field.type === "collateral") {
    const pledge = draft as CollateralDraft;
    const amount = parseInteger(pledge.declared_value_rub);
    const errors: Record<string, string> = {};
    if (amount.error) errors["collateral.declared_value_rub"] = amount.error;
    else if (amount.value === 0)
      errors["collateral.declared_value_rub"] = "Укажите стоимость больше нуля";
    const value: Collateral = {
      status: pledge.status as Collateral["status"],
      type: pledge.type as Collateral["type"],
      declared_value_rub: amount.value,
      description: pledge.description.trim() || null,
      owner_confirmed: pledge.owner_confirmed,
      encumbered: pledge.encumbered,
    };
    return { value, errors };
  }
  if (field.type === "integer") {
    const parsed = parseInteger(draft as string);
    return {
      value: parsed.value,
      errors: parsed.error ? { [field.name]: parsed.error } : {},
    };
  }
  if (field.type === "text")
    return { value: (draft as string).trim() || null, errors: {} };
  if (field.type === "date")
    return { value: (draft as string) || null, errors: {} };
  return { value: draft as boolean | string | null, errors: {} };
}

const pledgeKeys = [
  "status",
  "type",
  "declared_value_rub",
  "description",
  "owner_confirmed",
  "encumbered",
] as const;
const comparable = (field: FieldDescriptor, value: AnswerValue | undefined) => {
  if (field.type !== "collateral") return value ?? null;
  if (!value || typeof value !== "object") return null;
  return pledgeKeys.map((key) => value[key] ?? null);
};
export const sameAnswer = (
  field: FieldDescriptor,
  a: AnswerValue | undefined,
  b: AnswerValue | undefined,
) =>
  JSON.stringify(comparable(field, a)) === JSON.stringify(comparable(field, b));

/** A saved value the customer has actually given (an unchecked confirmation is not one). */
export function hasAnswer(
  field: FieldDescriptor,
  value: AnswerValue | undefined,
) {
  if (value === null || value === undefined || value === "") return false;
  return !field.must_be_true || value === true;
}

const optionLabel = (
  options: { value: string; label: string }[] | undefined,
  value: unknown,
) => options?.find((option) => option.value === value)?.label;

/** Read-only wording of a saved answer for the review stage; null when nothing has been given. */
export function formatAnswer(
  field: FieldDescriptor,
  value: AnswerValue | undefined,
): string | null {
  if (!hasAnswer(field, value)) return null;
  switch (field.type) {
    case "boolean":
      return field.must_be_true ? "Подтверждено" : value ? "Да" : "Нет";
    case "enum":
      return optionLabel(field.options, value) ?? String(value);
    case "integer":
      if (isMoney(field)) return rub(value as number);
      return field.name === "term_months" ? `${value} мес.` : String(value);
    case "date":
      return formatDay(value as string);
    case "text":
      return String(value);
    case "collateral": {
      const pledge = value as Collateral;
      const status = optionLabel(field.statuses, pledge.status) ?? null;
      if (pledge.status !== "declared") return status;
      return [
        status,
        optionLabel(field.types, pledge.type),
        pledge.declared_value_rub ? rub(pledge.declared_value_rub) : null,
        pledge.description,
        pledge.owner_confirmed
          ? "собственность подтверждена"
          : "собственность не подтверждена",
        pledge.encumbered ? "есть обременение" : "без обременения",
      ]
        .filter(Boolean)
        .join(" · ");
    }
  }
}

/** A source-owned answer as the client sees it: the source's value, where it comes from, or why it is missing. */
export type SourceReading = {
  value: string;
  /** Short origin tag for the review, empty when the value itself says what is missing. */
  origin: string;
  note: string;
  caution: boolean;
};

export function sourceReading(field: FieldDescriptor): SourceReading {
  const source = field.source;
  const shown = formatAnswer(field, source?.value ?? null);
  if (source?.name === "gosuslugi")
    return source.status === "available" && shown !== null
      ? {
          value: shown,
          origin: "подтверждено через Госуслуги",
          note: "Подтверждено через Госуслуги: в анкете не меняется.",
          caution: false,
        }
      : {
          value: "Нет подтверждения через Госуслуги",
          origin: "",
          note: "Полномочия не подтверждены через Госуслуги: компания добавлена без подтверждения, поэтому заявку по ней не отправить.",
          caution: true,
        };
  if (source?.status === "unavailable")
    return {
      value: shown ?? "Нет данных источника",
      origin: "реестр временно недоступен",
      note: "Реестр временно недоступен: значение уточнится после повторной проверки.",
      caution: true,
    };
  return shown === null
    ? {
        value: "Нет данных источника",
        origin: "",
        note: "Источник не передал значение: в анкете его не указывают.",
        caution: false,
      }
    : {
        value: shown,
        origin: "из открытых источников",
        note: "Из открытых источников: в анкете не меняется.",
        caution: false,
      };
}

/**
 * The term field as the purpose being chosen bounds it: a per-purpose maximum while that purpose is picked (saved or
 * not yet), otherwise the product's maximum. `scope` names what the range belongs to.
 */
export function termFor(
  field: FieldDescriptor,
  purpose: string | null,
  productMax: number | null | undefined,
  purposeLabel: string | undefined,
): { field: FieldDescriptor; scope: string } {
  const lowered = purpose ? field.max_by_purpose?.[purpose] : undefined;
  return {
    field: { ...field, max: lowered ?? productMax ?? field.max },
    scope:
      lowered !== undefined && purposeLabel
        ? `Для цели «${purposeLabel}»`
        : "Для продукта",
  };
}

const PLEDGE_LABELS: Record<string, string> = {
  type: "тип",
  declared_value_rub: "стоимость",
  description: "описание",
};

/** Where an answer path (as in missing_fields and field_issues) lives in the questionnaire. */
export function locate(stages: DialogStage[], path: string) {
  const [name, key] = path.split(".");
  if (name === "product_id")
    return { stage: 2, label: "Продукт и его условия" };
  const stage = stages.find((entry) =>
    entry.fields.some((field) => field.name === name),
  );
  const field = stage?.fields.find((entry) => entry.name === name);
  const label = field
    ? key
      ? `${field.label}: ${PLEDGE_LABELS[key] ?? key}`
      : field.label
    : path;
  return { stage: stage?.number ?? 1, label };
}

/** API validation paths are `answers.<name>[.<key>…]`; keep the answer path the inputs are keyed by. */
export function answerPaths(fields: Record<string, string>) {
  const mapped: Record<string, string> = {};
  for (const [path, message] of Object.entries(fields)) {
    const parts = path.replace(/^answers\./, "").split(".");
    const answer =
      parts[0] === "collateral" && parts[1]
        ? parts.slice(0, 2).join(".")
        : parts[0];
    mapped[answer] = message;
  }
  return mapped;
}
