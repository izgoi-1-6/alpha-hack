import React, { useState } from "react";
import { AuthorityVerification, Fixture, ConsentDocument } from "../../api";
import { Icon, DemoBadge, ErrorNotice } from "../../components";
export function Onboarding({
  fixtures,
  consents,
  busy,
  onVerify,
  onSubmit,
  onCancel,
  error,
}: {
  fixtures: Fixture[];
  consents: ConsentDocument[];
  busy: boolean;
  /** The mock Госуслуги check for the ИНН; null when it was refused (the error is shown) or superseded. */
  onVerify: (inn: string) => Promise<AuthorityVerification | null>;
  onSubmit: (inn: string, verificationId: string) => void;
  onCancel: () => void;
  error: string;
}) {
  const [inn, setInn] = useState(""),
    [accepted, setAccepted] = useState<Record<string, boolean>>({}),
    [verification, setVerification] = useState<AuthorityVerification | null>(
      null,
    );
  const selected = fixtures.find((f) => f.inn === inn);
  // A confirmation belongs to the ИНН it was given for: another ИНН needs its own.
  const verified = verification?.inn === inn ? verification : null;
  const innComplete = /^(\d{10}|\d{12})$/.test(inn);
  return (
    <>
      <div className="page-heading">
        <div className="eyebrow accent">Новая компания</div>
        <h1>Начнём с вашего бизнеса</h1>
        <p>Укажите ИНН — соберём сведения из демонстрационных источников.</p>
      </div>
      <div className="onboarding-grid">
        <section className="card onboarding-form">
          <div className="section-number">
            01 <span>Данные компании</span>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (verified) onSubmit(inn, verified.verification_id);
            }}
          >
            <label>
              ИНН компании или ИП
              <input
                className="inn-input"
                inputMode="numeric"
                pattern="[0-9]{10}|[0-9]{12}"
                maxLength={12}
                value={inn}
                onChange={(e) => setInn(e.target.value)}
                required
                placeholder="10 или 12 цифр"
                aria-describedby="inn-hint"
              />
            </label>
            <p id="inn-hint" className="field-hint">
              10 цифр для ООО, 12 — для ИП. Поддерживаются только демо-профили
              из списка.
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
            <div className="section-number consent-title">
              02 <span>Полномочия представителя</span>
            </div>
            {verified && (
              <div className="notice quiet" role="status">
                <Icon name="check" />
                <span>
                  Полномочия подтверждены через Госуслуги:{" "}
                  {verified.person_name}, {verified.role.toLowerCase()}.
                </span>
              </div>
            )}
            <div className="form-actions">
              <button
                className="button secondary"
                type="button"
                disabled={busy || !innComplete}
                onClick={async () => setVerification(await onVerify(inn))}
              >
                {verified
                  ? "Подтвердить заново"
                  : "Подтвердить через Госуслуги"}
              </button>
            </div>
            <div className="section-number consent-title">
              03 <span>Разрешения на проверку</span>
            </div>
            <div className="consents">
              {consents.map((doc) => (
                <label className="checkbox" key={doc.code}>
                  <input
                    type="checkbox"
                    checked={!!accepted[doc.code]}
                    onChange={(e) =>
                      setAccepted({ ...accepted, [doc.code]: e.target.checked })
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
            <div className="notice quiet">
              <Icon name="shield" />
              <span>
                Проверяем только реестр и обороты. Кредитная история на этом
                шаге не запрашивается.
              </span>
            </div>
            {error && <ErrorNotice error={error} />}
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
                disabled={
                  busy ||
                  !verified ||
                  consents.length !== 2 ||
                  !consents.every((c) => accepted[c.code])
                }
              >
                {busy ? "Проверяем компанию…" : "Добавить и проверить"}
                <Icon />
              </button>
            </div>
          </form>
        </section>
        <aside className="card fixture-panel">
          <div className="panel-title">
            <h2>Выберите демо-профиль</h2>
            <DemoBadge />
          </div>
          <p className="muted">
            Разные сценарии проверки — от полного профиля до недоступного
            источника.
          </p>
          <div className="fixture-list">
            {fixtures.map((f) => (
              <button
                key={f.fixture_id}
                className={f.inn === inn ? "active" : ""}
                onClick={() => setInn(f.inn)}
              >
                <span className="fixture-type">
                  {f.entity_type === "IP" ? "ИП" : "ООО"}
                </span>
                <span>
                  <b>
                    {f.name.replace(/^(ООО|ИП) «Демо /, "").replace(/»$/, "")}
                  </b>
                  <small>
                    {f.inn} ·{" "}
                    {f.registry_status === "inactive"
                      ? "Неактивная компания"
                      : f.registry_source_status === "unavailable"
                        ? "Реестр недоступен"
                        : f.turnover_source_status === "missing"
                          ? "Нет данных об обороте"
                          : "Демо-данные"}
                  </small>
                </span>
                {f.inn === inn && <Icon name="check" size={17} />}
              </button>
            ))}
          </div>
        </aside>
      </div>
    </>
  );
}
