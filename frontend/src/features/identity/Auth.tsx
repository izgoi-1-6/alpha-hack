import React, { useState } from "react";
import { api, User, errorMessage as message } from "../../api";
import { Icon, Brand, ErrorNotice } from "../../components";

/** The seeded profiles behind the quick-login buttons (their password is documented, never shown on the page). */
const QUICK_LOGINS = [
  { label: "Войти как клиент", email: "client@demo.local" },
  { label: "Войти как специалист", email: "officer@demo.local" },
  { label: "Новый клиент", email: "other@demo.local" },
];
const SEED_PASSWORD = "DemoCredit2026!";
export function Auth({ onAuth }: { onAuth: (u: User) => void }) {
  const [register, setRegister] = useState(false),
    [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [name, setName] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = register
        ? await api.register(email, password, name)
        : await api.login(email, password);
      onAuth(r.user);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function quickLogin(email: string) {
    setBusy(true);
    setError("");
    try {
      onAuth((await api.login(email, SEED_PASSWORD)).user);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-page">
      <aside className="auth-story">
        <Brand />
        <div className="story-content">
          <div className="eyebrow">Для предпринимателей и компаний</div>
          <h1>
            У вашего бизнеса
            <br />
            есть планы.
            <br />
            <span>Начнём маршрут.</span>
          </h1>
          <p>
            Соберите данные компании в одном месте и подготовьте следующий шаг к
            финансированию.
          </p>
          <div className="route-steps">
            <div>
              <b>01</b>
              <span>
                Войдите в кабинет<small>Ваши данные сохранятся</small>
              </span>
            </div>
            <div>
              <b>02</b>
              <span>
                Добавьте компанию<small>ИП или ООО по ИНН</small>
              </span>
            </div>
            <div>
              <b>03</b>
              <span>
                Проверьте сведения
                <small>Понятный статус каждого источника</small>
              </span>
            </div>
          </div>
        </div>
        <div className="story-foot">
          <Icon name="shield" />
          Кредитная история запрашивается только с вашего согласия.
        </div>
      </aside>
      <main className="auth-main">
        <div className="auth-top">
          <span>Кабинет для бизнеса</span>
          <span>ИП и ООО</span>
        </div>
        <div className="auth-card">
          <div className="eyebrow accent">Кредитный маршрут</div>
          <h2>{register ? "Создать аккаунт" : "С возвращением"}</h2>
          <p className="muted">
            {register
              ? "Добавьте компанию и подберите для неё финансирование."
              : "Войдите, чтобы продолжить работу с компанией."}
          </p>
          <div className="tabs" aria-label="Режим входа">
            <button
              className={!register ? "selected" : ""}
              onClick={() => {
                setRegister(false);
                setError("");
              }}
            >
              Вход
            </button>
            <button
              className={register ? "selected" : ""}
              onClick={() => {
                setRegister(true);
                setError("");
              }}
            >
              Регистрация
            </button>
          </div>
          <form onSubmit={submit}>
            {register && (
              <label>
                Ваше имя
                <input
                  autoComplete="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  maxLength={100}
                  placeholder="Как к вам обращаться"
                />
              </label>
            )}
            <label>
              Электронная почта
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                maxLength={254}
                placeholder="name@company.ru"
              />
            </label>
            <label>
              Пароль
              <input
                type="password"
                autoComplete={register ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={10}
                maxLength={128}
                required
                placeholder={
                  register ? "Не менее 10 символов" : "Введите пароль"
                }
              />
            </label>
            {error && <ErrorNotice error={error} />}
            <button className="button primary wide" disabled={busy}>
              {busy
                ? "Подождите…"
                : register
                  ? "Создать аккаунт"
                  : "Войти в кабинет"}
              <Icon />
            </button>
          </form>
          <div className="quick-access">
            <div className="quick-heading">
              <Icon name="route" />
              <b>Быстрый вход</b>
            </div>
            <p>
              Готовые профили: клиент с компаниями, кредитный специалист или
              новый клиент без компаний.
            </p>
            <div className="quick-buttons">
              {QUICK_LOGINS.map((profile) => (
                <button
                  key={profile.email}
                  disabled={busy}
                  onClick={() => void quickLogin(profile.email)}
                >
                  {profile.label} <Icon size={16} />
                </button>
              ))}
            </div>
          </div>
          <p className="auth-note">
            Не вводите реальные персональные данные или банковские реквизиты:
            сервис работает с синтетическими профилями компаний.
          </p>
        </div>
        <footer>
          © 2026 Кредитный маршрут <span>Финансирование для бизнеса</span>
        </footer>
      </main>
    </div>
  );
}
