import React, { useState } from "react";
import { api, User, errorMessage as message } from "../../api";
import { Icon, Brand, DemoBadge, ErrorNotice } from "../../components";
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
  async function demo(email: string) {
    setBusy(true);
    setError("");
    try {
      onAuth((await api.login(email, "DemoCredit2026!")).user);
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
          Только синтетические данные. Без обращения в банк.
        </div>
      </aside>
      <main className="auth-main">
        <div className="auth-top">
          <span>Демонстрационный кабинет</span>
          <DemoBadge />
        </div>
        <div className="auth-card">
          <div className="eyebrow accent">Кредитный маршрут</div>
          <h2>{register ? "Создать аккаунт" : "С возвращением"}</h2>
          <p className="muted">
            {register
              ? "Добавьте компанию и проверьте её демо-профиль."
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
          <div className="demo-access">
            <div className="demo-heading">
              <Icon name="route" />
              <b>Попробуйте без регистрации</b>
            </div>
            <p>Готовые синтетические профили для знакомства с сервисом.</p>
            <div className="demo-buttons">
              <button disabled={busy} onClick={() => demo("client@demo.local")}>
                Демо-клиент <Icon size={16} />
              </button>
              <button
                disabled={busy}
                onClick={() => demo("officer@demo.local")}
              >
                Специалист <Icon size={16} />
              </button>
              <button disabled={busy} onClick={() => demo("other@demo.local")}>
                Новый клиент <Icon size={16} />
              </button>
            </div>
            <details>
              <summary>Данные для ручного входа</summary>
              <p>
                client@demo.local · other@demo.local · officer@demo.local
                <br />
                Пароль: <code>DemoCredit2026!</code>
              </p>
            </details>
          </div>
          <p className="auth-note">
            Локальная демонстрация. Не вводите реальные персональные данные или
            банковские реквизиты.
          </p>
        </div>
        <footer>
          © 2026 Кредитный маршрут <span>Прототип для бизнеса</span>
        </footer>
      </main>
    </div>
  );
}
