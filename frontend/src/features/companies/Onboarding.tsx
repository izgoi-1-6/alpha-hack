import { useEffect, useRef, useState } from "react";
import { AuthorityVerification, Fixture, ConsentDocument } from "../../api";
import { Icon, ErrorNotice } from "../../components";
import { formatTime } from "../applications/format";
import { GosuslugiDialog } from "./GosuslugiDialog";
import "./onboarding.css";

/** «Сильный бизнес» for «ООО «Сильный бизнес»»: the type chip beside it already says ИП or ООО. */
const shortName = (name: string) =>
  name.match(/^(?:ООО|ИП)\s+«(.+)»$/)?.[1] ?? name;

function fixtureNote(fixture: Fixture) {
  if (fixture.registry_status === "inactive") return "Неактивная компания";
  if (fixture.registry_source_status === "unavailable")
    return "Реестр недоступен";
  if (fixture.turnover_source_status === "missing")
    return "Нет данных об обороте";
  return "Полные сведения";
}

/**
 * Adding a company in three steps: choose the ИНН, confirm the representative's authority through Госуслуги (a
 * dialog with the person and role the check returns), give both consents. The confirmation belongs to the ИНН it
 * was given for: choosing another company discards it.
 */
export function Onboarding({
  fixtures,
  consents,
  busy,
  onSubmit,
  onCancel,
  onUnauthorized,
  error,
  onClearError,
}: {
  fixtures: Fixture[];
  consents: ConsentDocument[];
  busy: boolean;
  onSubmit: (inn: string, verificationId: string) => void;
  onCancel: () => void;
  onUnauthorized: () => void;
  /** The last refused add (e.g. a company already added); it goes once the client chooses or confirms again. */
  error: string;
  onClearError: () => void;
}) {
  const [inn, setInn] = useState(""),
    [accepted, setAccepted] = useState<Record<string, boolean>>({}),
    [verification, setVerification] = useState<AuthorityVerification | null>(
      null,
    ),
    [checking, setChecking] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const confirmed = useRef<HTMLDivElement>(null);
  const selected = fixtures.find((f) => f.inn === inn);
  const verified = verification?.inn === inn ? verification : null;
  const innComplete = /^(\d{10}|\d{12})$/.test(inn);
  const consented =
    consents.length === 2 && consents.every((c) => accepted[c.code]);
  const remaining = [
    !innComplete && "выбрать компанию или ввести ИНН",
    !verified && "подтвердить полномочия через Госуслуги",
    !consented && "отметить оба разрешения",
  ].filter(Boolean);

  // When the dialog closes, focus returns to the step: the confirmation if one was given, else its button.
  const wasChecking = useRef(false);
  useEffect(() => {
    if (wasChecking.current && !checking)
      (verified ? confirmed : trigger).current?.focus();
    wasChecking.current = checking;
  }, [checking]);

  function choose(next: string) {
    setInn(next);
    if (next !== verification?.inn) setVerification(null);
    if (error) onClearError();
  }

  return (
    <>
      <div className="page-heading">
        <div className="eyebrow accent">Новая компания</div>
        <h1>Начнём с вашего бизнеса</h1>
        <p>
          Укажите ИНН — соберём сведения о компании из реестра и открытых
          источников.
        </p>
      </div>
      <div className="onboarding-grid">
        <section className="card onboarding-form">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (verified) onSubmit(inn, verified.verification_id);
            }}
          >
            <div className="section-number">
              01 <span>Данные компании</span>
            </div>
            <label>
              ИНН компании или ИП
              <input
                className="inn-input"
                inputMode="numeric"
                pattern="[0-9]{10}|[0-9]{12}"
                maxLength={12}
                value={inn}
                onChange={(e) => choose(e.target.value)}
                required
                placeholder="10 или 12 цифр"
                aria-describedby="inn-hint"
              />
            </label>
            <p id="inn-hint" className="field-hint">
              10 цифр для ООО, 12 — для ИП. Доступны компании из списка.
            </p>
            {selected && (
              <div className="selected-fixture">
                <Icon name="building" />
                <div>
                  <strong>{selected.name}</strong>
                  <small>
                    {selected.entity_type === "IP"
                      ? "Индивидуальный предприниматель"
                      : "Общество с ограниченной ответственностью"}
                  </small>
                </div>
              </div>
            )}

            <section
              id="gosuslugi-step"
              className="authority-step"
              aria-labelledby="authority-title"
              data-tour="gosuslugi"
            >
              <div className="section-number consent-title">
                02 <span id="authority-title">Полномочия представителя</span>
              </div>
              {verified ? (
                <div className="authority-confirmed">
                  <div
                    ref={confirmed}
                    className="authority-confirmed-text"
                    role="status"
                    tabIndex={-1}
                  >
                    <span className="authority-check" aria-hidden="true">
                      <Icon name="check" size={18} />
                    </span>
                    <div>
                      <strong>Полномочия подтверждены через Госуслуги</strong>
                      <p>
                        {verified.person_name} · {verified.role}
                      </p>
                      <small>
                        ИНН {verified.inn} · подтверждение действует до{" "}
                        {formatTime(new Date(verified.expires_at))}
                      </small>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="text-button"
                    disabled={busy}
                    onClick={() => setChecking(true)}
                  >
                    Подтвердить заново
                  </button>
                </div>
              ) : (
                <div className="authority-pending">
                  <p className="field-note">
                    Подтвердите, что представляете компанию: Госуслуги передадут
                    ваши ФИО и должность. Без подтверждения компанию не
                    добавить.
                  </p>
                  <button
                    ref={trigger}
                    className="button secondary"
                    type="button"
                    disabled={busy || !innComplete}
                    onClick={() => setChecking(true)}
                  >
                    <Icon name="shield" size={18} />
                    Подтвердить через Госуслуги
                  </button>
                </div>
              )}
            </section>

            <section
              id="onboarding-consents"
              aria-labelledby="consents-title"
              data-tour="consents"
            >
              <div className="section-number consent-title">
                03 <span id="consents-title">Разрешения на проверку</span>
              </div>
              <div className="consents">
                {consents.map((doc) => (
                  <label className="checkbox" key={doc.code}>
                    <input
                      type="checkbox"
                      checked={!!accepted[doc.code]}
                      onChange={(e) =>
                        setAccepted({
                          ...accepted,
                          [doc.code]: e.target.checked,
                        })
                      }
                      required
                    />
                    <span>
                      {doc.text}
                      <small>Версия {doc.version}</small>
                    </span>
                  </label>
                ))}
              </div>
            </section>
            <div className="notice quiet">
              <Icon name="shield" />
              <span>
                Проверяем только реестр и обороты. Кредитная история на этом
                шаге не запрашивается.
              </span>
            </div>
            {error && <ErrorNotice error={error} />}
            {remaining.length > 0 && (
              <p id="onboarding-remaining" className="onboarding-remaining">
                Осталось: {remaining.join("; ")}.
              </p>
            )}
            <div className="form-actions">
              <button
                className="button secondary"
                type="button"
                onClick={onCancel}
              >
                Отмена
              </button>
              <button
                className="button primary"
                disabled={busy || remaining.length > 0}
                aria-describedby={
                  remaining.length ? "onboarding-remaining" : undefined
                }
              >
                {busy ? "Проверяем компанию…" : "Добавить и проверить"}
                <Icon />
              </button>
            </div>
          </form>
        </section>
        <aside
          className="card fixture-panel"
          aria-labelledby="fixtures-title"
          data-tour="choose-company"
        >
          <div className="panel-title">
            <h2 id="fixtures-title">Выберите компанию</h2>
          </div>
          <p className="muted">
            Компании с разными сценариями проверки — от полных сведений до
            недоступного источника.
          </p>
          <div className="fixture-list">
            {fixtures.map((f) => (
              <button
                key={f.fixture_id}
                type="button"
                className={f.inn === inn ? "active" : ""}
                aria-pressed={f.inn === inn}
                onClick={() => choose(f.inn)}
              >
                <span className="fixture-type">
                  {f.entity_type === "IP" ? "ИП" : "ООО"}
                </span>
                <span>
                  <b>{shortName(f.name)}</b>
                  <small>
                    {f.inn} · {fixtureNote(f)}
                  </small>
                </span>
                {f.inn === inn && <Icon name="check" size={17} />}
              </button>
            ))}
          </div>
        </aside>
      </div>
      {checking && (
        <GosuslugiDialog
          inn={inn}
          companyName={selected?.name ?? null}
          onConfirm={(next) => {
            setVerification(next);
            setChecking(false);
            if (error) onClearError();
          }}
          onClose={() => setChecking(false)}
          onUnauthorized={onUnauthorized}
        />
      )}
    </>
  );
}
