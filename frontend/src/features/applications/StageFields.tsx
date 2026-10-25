import { FieldDescriptor } from "../../api";
import { DemoBadge } from "../../components";
import { keepAmountsTogether, rub } from "./format";
import {
  CollateralDraft,
  FieldDraft,
  formatAnswer,
  formatDay,
  isMoney,
  parseInteger,
} from "./fields";

type FieldProps = {
  field: FieldDescriptor;
  draft: FieldDraft;
  /** Messages by answer path: input errors first, then the server's submit blockers worth showing now. */
  messages: Record<string, string>;
  disabled: boolean;
  onChange: (draft: FieldDraft) => void;
};

const HINTS: Record<string, string> = {
  actual_address: "Синтетический адрес: реальные данные не нужны.",
  actual_activity: "Например, оптовая торговля или производство мебели.",
  employees: "Сотрудники в штате на сегодня.",
  monthly_debt_payment_rub:
    "Сумма ежемесячных платежей по кредитам, лизингу и займам. Если их нет, укажите 0.",
  tax_debt_rub: "Если задолженности нет, укажите 0.",
  obligations_note: "Например, лизинг оборудования до конца 2027 года.",
  representative_name: "Только синтетическое имя: паспортные данные не нужны.",
};

/** The input id of an answer path; the wizard uses it to move focus to the first invalid field. */
export const idOf = (path: string) => "answer-" + path.replace(/\./g, "-");
const describedBy = (...ids: (string | false | null | undefined)[]) =>
  ids.filter(Boolean).join(" ") || undefined;

function Optional({ field }: { field: FieldDescriptor }) {
  return field.required ? null : (
    <span className="optional"> необязательно</span>
  );
}

function Message({
  path,
  messages,
}: {
  path: string;
  messages: Record<string, string>;
}) {
  return messages[path] ? (
    <p className="field-error" id={idOf(path) + "-error"}>
      {keepAmountsTogether(messages[path])}
    </p>
  ) : null;
}

function Choices({
  name,
  options,
  value,
  disabled,
  onChange,
}: {
  name: string;
  options: { value: string; label: string }[];
  value: string | null;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div className="choices">
      {options.map((option) => (
        <label
          key={option.value}
          className={"choice" + (value === option.value ? " chosen" : "")}
        >
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            disabled={disabled}
            onChange={() => onChange(option.value)}
          />
          <span>{option.label}</span>
        </label>
      ))}
    </div>
  );
}

function numberHint(field: FieldDescriptor, draft: string) {
  const parsed = parseInteger(draft);
  const range =
    field.name === "requested_amount_rub" &&
    field.min != null &&
    field.max != null
      ? `Для продукта: от ${rub(field.min)} до ${rub(field.max)}.`
      : field.name === "term_months" && field.min != null && field.max != null
        ? `Для продукта: от ${field.min} до ${field.max} мес.`
        : null;
  // A prefilled source value already shows its formatted amount in the source note.
  const sameAsSource =
    field.source?.value != null && parsed.value === field.source.value;
  const preview =
    isMoney(field) && parsed.value !== null && !parsed.error && !sameAsSource
      ? `Указано: ${rub(parsed.value)}.`
      : null;
  return [preview, range, HINTS[field.name]].filter(Boolean).join(" ") || null;
}

/** Stage-3 finance answers next to the turnover source; an edit of a known value is flagged for the officer. */
function SourceNote({
  field,
  draft,
}: {
  field: FieldDescriptor;
  draft: string;
}) {
  const source = field.source!;
  const known = source.value !== null && source.status !== "unavailable";
  const shown =
    source.value === null
      ? "нет значения"
      : field.type === "date"
        ? formatDay(String(source.value))
        : rub(Number(source.value));
  const current =
    field.type === "integer" ? parseInteger(draft).value : draft || null;
  const differs = known && current !== null && current !== source.value;
  return (
    <div className={"source-note" + (differs || !known ? " caution" : "")}>
      <span className="source-line">
        <b>Демо-источник оборотов</b> · {shown}
        <DemoBadge />
      </span>
      <p>
        {!known
          ? "Источник не передал значение: укажите его сами — заявленные сведения проверит кредитный специалист."
          : differs
            ? "Значение отличается от источника: его проверит кредитный специалист, исходные данные сохранятся."
            : current === null
              ? "Поле пустое: укажите значение из источника или своё."
              : "Значение подставлено из источника."}
      </p>
    </div>
  );
}

function TextLikeField({
  field,
  draft,
  messages,
  disabled,
  onChange,
}: FieldProps) {
  const id = idOf(field.name);
  const value = draft as string;
  const hint =
    field.type === "integer" ? numberHint(field, value) : HINTS[field.name];
  const error = messages[field.name];
  const common = {
    id,
    value,
    disabled,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": describedBy(
      hint && id + "-hint",
      field.source && id + "-source",
      error && id + "-error",
    ),
  };
  return (
    <div className="field">
      <label htmlFor={id}>
        {field.label}
        <Optional field={field} />
      </label>
      {field.type === "text" && (field.max_length ?? 0) > 300 ? (
        <textarea
          {...common}
          rows={3}
          maxLength={field.max_length}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          {...common}
          type={field.type === "date" ? "date" : "text"}
          inputMode={field.type === "integer" ? "numeric" : undefined}
          autoComplete="off"
          maxLength={field.type === "text" ? field.max_length : undefined}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      {hint && (
        <p className="field-note" id={id + "-hint"}>
          {hint}
        </p>
      )}
      {field.source && (
        <div id={id + "-source"}>
          <SourceNote field={field} draft={value} />
        </div>
      )}
      <Message path={field.name} messages={messages} />
    </div>
  );
}

function BooleanField({
  field,
  draft,
  messages,
  disabled,
  onChange,
}: FieldProps) {
  const id = idOf(field.name);
  if (field.must_be_true)
    return (
      <div className="field">
        <label className="check-row">
          <input
            type="checkbox"
            checked={draft === true}
            disabled={disabled}
            aria-invalid={messages[field.name] ? true : undefined}
            aria-describedby={messages[field.name] ? id + "-error" : undefined}
            onChange={(event) => onChange(event.target.checked)}
          />
          <span>{field.label}</span>
        </label>
        <Message path={field.name} messages={messages} />
      </div>
    );
  return (
    <fieldset
      className="field choice-field"
      aria-describedby={messages[field.name] ? id + "-error" : undefined}
    >
      <legend>
        {field.label}
        <Optional field={field} />
      </legend>
      <Choices
        name={id}
        value={draft === null ? null : draft ? "yes" : "no"}
        options={[
          { value: "yes", label: "Да" },
          { value: "no", label: "Нет" },
        ]}
        disabled={disabled}
        onChange={(value) => onChange(value === "yes")}
      />
      <Message path={field.name} messages={messages} />
    </fieldset>
  );
}

function EnumField({ field, draft, messages, disabled, onChange }: FieldProps) {
  const id = idOf(field.name);
  return (
    <fieldset
      className="field choice-field"
      aria-describedby={messages[field.name] ? id + "-error" : undefined}
    >
      <legend>
        {field.label}
        <Optional field={field} />
      </legend>
      <Choices
        name={id}
        value={draft as string | null}
        options={field.options ?? []}
        disabled={disabled}
        onChange={onChange}
      />
      <Message path={field.name} messages={messages} />
    </fieldset>
  );
}

function CollateralField({
  field,
  draft,
  messages,
  disabled,
  onChange,
}: FieldProps) {
  const pledge = draft as CollateralDraft;
  const update = (patch: Partial<CollateralDraft>) =>
    onChange({ ...pledge, ...patch });
  const declared = pledge.status === "declared";
  const valueId = idOf("collateral.declared_value_rub");
  const descriptionId = idOf("collateral.description");
  const valueHint = numberHint(
    { ...field, name: "declared_value_rub", type: "integer" },
    pledge.declared_value_rub,
  );
  return (
    <fieldset className="field collateral-field">
      <legend>
        {field.label}
        <Optional field={field} />
      </legend>
      <p
        className={
          "field-note" + (field.required && !declared ? " caution" : "")
        }
      >
        {field.required
          ? declared
            ? "Заявленную стоимость нужно будет подтвердить документами об оценке и праве собственности."
            : "Для кредита с залогом заявите залог: тип, стоимость и описание — без них заявку не отправить."
          : "Продукт без залога: сведения о залоге не влияют на решение."}
      </p>
      <Choices
        name={idOf("collateral.status")}
        value={pledge.status}
        options={field.statuses ?? []}
        disabled={disabled}
        onChange={(status) =>
          update(
            status === "declared"
              ? {
                  status,
                  owner_confirmed: pledge.owner_confirmed ?? false,
                  encumbered: pledge.encumbered ?? false,
                }
              : { status },
          )
        }
      />
      {declared && (
        <div className="collateral-details">
          <fieldset className="choice-field">
            <legend>Тип залога</legend>
            <Choices
              name={idOf("collateral.type")}
              value={pledge.type}
              options={field.types ?? []}
              disabled={disabled}
              onChange={(type) => update({ type })}
            />
            <Message path="collateral.type" messages={messages} />
          </fieldset>
          <div className="field">
            <label htmlFor={valueId}>Заявленная стоимость, ₽</label>
            <input
              id={valueId}
              inputMode="numeric"
              autoComplete="off"
              value={pledge.declared_value_rub}
              disabled={disabled}
              aria-invalid={
                messages["collateral.declared_value_rub"] ? true : undefined
              }
              aria-describedby={describedBy(
                valueHint && valueId + "-hint",
                messages["collateral.declared_value_rub"] && valueId + "-error",
              )}
              onChange={(event) =>
                update({ declared_value_rub: event.target.value })
              }
            />
            {valueHint && (
              <p className="field-note" id={valueId + "-hint"}>
                {valueHint}
              </p>
            )}
            <Message path="collateral.declared_value_rub" messages={messages} />
          </div>
          <div className="field">
            <label htmlFor={descriptionId}>Описание залога</label>
            <textarea
              id={descriptionId}
              rows={2}
              maxLength={field.description_max_length}
              value={pledge.description}
              disabled={disabled}
              aria-invalid={
                messages["collateral.description"] ? true : undefined
              }
              aria-describedby={
                messages["collateral.description"]
                  ? descriptionId + "-error"
                  : undefined
              }
              onChange={(event) => update({ description: event.target.value })}
            />
            <Message path="collateral.description" messages={messages} />
          </div>
          <label className="check-row">
            <input
              type="checkbox"
              checked={pledge.owner_confirmed === true}
              disabled={disabled}
              onChange={(event) =>
                update({ owner_confirmed: event.target.checked })
              }
            />
            <span>Подтверждаю собственность на залог</span>
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={pledge.encumbered === true}
              disabled={disabled}
              onChange={(event) => update({ encumbered: event.target.checked })}
            />
            <span>Есть обременение</span>
          </label>
          <p className="field-note">
            Если собственность не подтверждена или есть обременение, заявку
            проверит кредитный специалист. Доля учредителя не заменяет согласия
            поручителя.
          </p>
        </div>
      )}
    </fieldset>
  );
}

const SOURCE_NOTES: Record<string, string> = {
  registry: "Из открытых источников: в анкете не меняется.",
  gosuslugi: "Подтверждено через Госуслуги: в анкете не меняется.",
};

/** A source-owned answer (registry, Госуслуги): the source's value as text. It has no input, so it is never sent. */
function ReadOnlyField({ field }: { field: FieldDescriptor }) {
  const source = field.source;
  const value =
    formatAnswer(field, source?.value ?? null) ?? "Нет данных источника";
  const note =
    source?.status === "unavailable"
      ? "Реестр временно недоступен: значение уточнится после повторной проверки."
      : SOURCE_NOTES[source?.name ?? ""];
  return (
    <fieldset className="field read-only-field">
      <legend>{field.label}</legend>
      <p>{value}</p>
      {note && <p className="field-note">{note}</p>}
    </fieldset>
  );
}

/** The widget for one server-declared field; the server owns which fields exist and what blocks submission. */
export function StageField(props: FieldProps) {
  if (props.field.read_only) return <ReadOnlyField field={props.field} />;
  switch (props.field.type) {
    case "boolean":
      return <BooleanField {...props} />;
    case "enum":
      return <EnumField {...props} />;
    case "collateral":
      return <CollateralField {...props} />;
    default:
      return <TextLikeField {...props} />;
  }
}
