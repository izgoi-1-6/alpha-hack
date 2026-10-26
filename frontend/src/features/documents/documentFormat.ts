import {
  ApplicationDocument,
  ApplicationStatus,
  DocumentStatus,
  DocumentType,
} from "../../api";
import { formatDate, formatTime } from "../applications/format";

const NBSP = "\u00a0";

/** The checklist's names, as the server writes them in its notifications. Synthetic evidence, not legal requirements. */
export const DOCUMENT_TITLE: Record<DocumentType, string> = {
  BANK_STATEMENT: "Банковская выписка",
  FINANCIAL_REPORT: "Финансовая отчётность",
  COLLATERAL_OWNERSHIP: "Документ о праве собственности на залог",
  COLLATERAL_VALUATION: "Отчёт об оценке залога",
};
export const documentTitle = (type: string) =>
  DOCUMENT_TITLE[type as DocumentType] ?? type;

export const DOCUMENT_HINT: Record<DocumentType, string> = {
  BANK_STATEMENT: "Движение по расчётному счёту компании.",
  FINANCIAL_REPORT: "Отчётность за период, указанный в анкете.",
  COLLATERAL_OWNERSHIP: "Подтверждает, что предмет залога принадлежит компании.",
  COLLATERAL_VALUATION: "По нему специалист укажет проверенную стоимость залога.",
};

type Tone = "success" | "warning" | "neutral" | "danger";

/** A revision's status in words. An unreviewed current file reads «Загружен» until the packet is sent. */
export function documentStatus(
  status: DocumentStatus,
  applicationStatus: ApplicationStatus,
): { label: string; tone: Tone } {
  switch (status) {
    case "UPLOADED":
      return applicationStatus === "DOCS_UPLOADED"
        ? { label: "На проверке", tone: "neutral" }
        : { label: "Загружен", tone: "neutral" };
    case "ACCEPTED":
      return { label: "Принят", tone: "success" };
    case "REJECTED":
      return { label: "Отклонён", tone: "danger" };
    case "SUPERSEDED":
      return { label: "Заменён", tone: "neutral" };
    case "DELETED":
      return { label: "Удалён", tone: "neutral" };
  }
}

export const MEDIA_LABEL: Record<ApplicationDocument["media_type"], string> = {
  "application/pdf": "PDF",
  "image/jpeg": "JPEG",
  "image/png": "PNG",
};

/** «467 Б», «12,4 КБ», «3,1 МБ» with a non-breaking space before the unit. */
export function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes}${NBSP}Б`;
  const [value, unit] =
    bytes < 1024 * 1024 ? [bytes / 1024, "КБ"] : [bytes / 1024 / 1024, "МБ"];
  return `${value.toFixed(1).replace(".", ",")}${NBSP}${unit}`;
}

/** The SHA-256 short form for reading aloud or comparing by eye; the full digest goes in the title. */
export const shortHash = (sha256: string) =>
  `${sha256.slice(0, 8)}…${sha256.slice(-4)}`;

/** A date with its time: «7 ноября 2026 г., 12:00». */
export const formatMoment = (value: string) =>
  `${formatDate(value)}, ${formatTime(new Date(value))}`;

/** One line of file facts: type, size and when it arrived. */
export const fileFacts = (document: ApplicationDocument) =>
  `${MEDIA_LABEL[document.media_type] ?? document.media_type} · ${fileSize(document.size_bytes)} · загружен ${formatMoment(document.created_at)}`;

export const MAX_FILE_BYTES = 20 * 1024 * 1024;
const MEDIA_BY_EXTENSION: Record<string, string> = {
  pdf: "application/pdf",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
};
export const ACCEPTED_FILES = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";

/**
 * A convenience check before sending: an allowed extension whose type the browser agrees with, at most 20 MiB.
 * The server stays the authority for everything else (content, structure, markup) and its refusal is shown as is.
 */
export function fileProblem(file: File): string | null {
  const extension = file.name.includes(".")
    ? file.name.split(".").pop()!.toLowerCase()
    : "";
  const expected = MEDIA_BY_EXTENSION[extension];
  if (!expected)
    return "Этот тип файла не подходит: можно загрузить только PDF, JPEG или PNG.";
  if (file.type !== expected)
    return "Тип файла не совпадает с его расширением: можно загрузить только PDF, JPEG или PNG.";
  if (file.size > MAX_FILE_BYTES)
    return "Файл больше 20 МБ: загрузите файл размером до 20 МБ.";
  if (file.size === 0) return "Файл пустой: выберите другой файл.";
  return null;
}
