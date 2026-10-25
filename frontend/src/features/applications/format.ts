import { Application, ApplicationStatus } from "../../api";

const NBSP = " ";

/** Integer RUB with non-breaking group and currency spaces, so an amount never wraps mid-number. */
export const rub = (value: number) =>
  new Intl.NumberFormat("ru-RU").format(value).replace(/\s/g, NBSP) +
  NBSP +
  "₽";

/** An amount that may be unknown: «нет значения» instead of a figure. */
export const rubOrNone = (value: number | null) =>
  value === null ? "нет значения" : rub(value);

/** Server texts format amounts with ordinary spaces; keep their digit groups and the ruble sign together. */
export const keepAmountsTogether = (text: string) =>
  text
    .replace(/(\d) (?=\d{3}(?!\d))/g, "$1" + NBSP)
    .replace(/(\d) ₽/g, "$1" + NBSP + "₽");

/** A signed RUB difference: «+100 000 ₽», «−50 000 ₽», «0 ₽». */
export const signedRub = (value: number) =>
  (value > 0 ? "+" : value < 0 ? "−" : "") + rub(Math.abs(value));

export const RISK = {
  low: "низкий риск",
  medium: "средний риск",
  high: "высокий риск",
};

/** «1 балл», «2 балла», «65 баллов». */
export const points = (n: number) => {
  const tail = n % 100;
  const last = n % 10;
  const word =
    tail >= 11 && tail <= 14
      ? "баллов"
      : last === 1
        ? "балл"
        : last >= 2 && last <= 4
          ? "балла"
          : "баллов";
  return `${n} ${word}`;
};

/** «25 октября 2026 г.» with the year suffix kept on the year's line. */
export const formatDate = (value: string) =>
  new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
  })
    .format(new Date(value))
    .replace(/\s(?=г\.$)/, NBSP);

export const formatDateTime = (value: string) =>
  new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));

export const formatTime = (value: Date) =>
  new Intl.DateTimeFormat("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(value);

type Tone = "success" | "warning" | "neutral" | "danger";

/** Plain-language status vocabulary: a short pill label and the page headline. Every tone is paired with text. */
export const STATUS: Record<
  ApplicationStatus,
  { label: string; headline: string; tone: Tone }
> = {
  DRAFT: {
    label: "Черновик",
    headline: "Анкета не отправлена",
    tone: "neutral",
  },
  CHECKING: {
    label: "Проверяется",
    headline: "Заявка проверяется",
    tone: "neutral",
  },
  WAIT_EXTERNAL: {
    label: "Ждём демо-источник",
    headline: "Ждём ответа демо-источника",
    tone: "warning",
  },
  NEED_INFO: {
    label: "Нужны сведения",
    headline: "Нужны дополнительные сведения",
    tone: "warning",
  },
  MANUAL_REVIEW: {
    label: "На рассмотрении",
    headline: "Заявка на рассмотрении у специалиста",
    tone: "neutral",
  },
  PREAPPROVED: {
    label: "Предварительно одобрена",
    headline: "Заявка предварительно одобрена",
    tone: "success",
  },
  DOCS_UPLOADED: {
    label: "Документы на проверке",
    headline: "Документы на проверке",
    tone: "neutral",
  },
  DOCS_REWORK: {
    label: "Замена документов",
    headline: "Нужно заменить документы",
    tone: "warning",
  },
  APPROVED: {
    label: "Одобрена (демо)",
    headline: "Заявка одобрена (демонстрационное решение)",
    tone: "success",
  },
  REJECTED: { label: "Отказ", headline: "По заявке отказ", tone: "danger" },
  CANCELLED: {
    label: "Отменена",
    headline: "Заявка отменена",
    tone: "neutral",
  },
  EXPIRED: {
    label: "Срок истёк",
    headline: "Срок предварительного одобрения истёк",
    tone: "neutral",
  },
};

export const statusLabel = (status: ApplicationStatus) =>
  STATUS[status]?.label ?? status;

const DOCUMENTS: Record<string, string> = {
  BANK_STATEMENT: "банковская выписка",
  FINANCIAL_REPORT: "финансовая отчётность",
  COLLATERAL_OWNERSHIP: "право собственности на залог",
  COLLATERAL_VALUATION: "оценка залога",
};
export const documentList = (codes: string[] | undefined) =>
  (codes ?? []).map((code) => DOCUMENTS[code] ?? code).join(", ");

/** One short next step per state, used by the list rows and the status page. */
export function nextStep(application: Application): string {
  const request = application.open_info_request;
  switch (application.status) {
    case "DRAFT":
      return `Продолжите анкету: шаг ${application.current_stage} из 6`;
    case "CHECKING":
      return "Дождитесь результата проверки";
    case "WAIT_EXTERNAL":
      return "Повторите проверку: демо-источник был недоступен";
    case "NEED_INFO":
      return request?.kind === "trusted_source"
        ? "Повторите проверку: нужен повторный запрос к демо-источнику"
        : "Ответьте на запрос сведений";
    case "MANUAL_REVIEW":
      return "Дождитесь решения кредитного специалиста";
    case "PREAPPROVED":
      return application.preapproval_expires_at
        ? `Подготовьте документы до ${formatDate(application.preapproval_expires_at)}`
        : "Подготовьте документы";
    case "DOCS_UPLOADED":
      return "Дождитесь проверки документов";
    case "DOCS_REWORK":
      return "Замените отклонённые документы";
    case "APPROVED":
      return "Демонстрационное решение: деньги не перечисляются";
    case "REJECTED":
      return "Можно подобрать другой продукт";
    case "CANCELLED":
      return "Можно начать новую заявку из подбора";
    case "EXPIRED":
      return "Создайте новую заявку из подбора";
  }
}

export const productName = (application: Pick<Application, "product">) =>
  application.product.name ?? "Демо-продукт";
