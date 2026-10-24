import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  api,
  ApiError,
  Company,
  CompanyResult,
  ConsentDocument,
  Fixture,
  User,
  errorMessage as message,
} from "./api";
import { Brand, Icon, DemoBadge, Loading, ErrorNotice } from "./components";
import { Auth } from "./features/identity/Auth";
import { Onboarding } from "./features/companies/Onboarding";
import { CompanyDetail } from "./features/companies/CompanyDetail";
import { Recommendations } from "./features/recommendations/Recommendations";
import "./styles.css";
function App() {
  const [user, setUser] = useState<User | null>(null),
    [booting, setBooting] = useState(true),
    [bootError, setBootError] = useState(""),
    [companies, setCompanies] = useState<Company[]>([]),
    [fixtures, setFixtures] = useState<Fixture[]>([]),
    [consents, setConsents] = useState<ConsentDocument[]>([]),
    [data, setData] = useState<CompanyResult | null>(null),
    [loading, setLoading] = useState(false),
    [loadError, setLoadError] = useState(""),
    [actionError, setActionError] = useState(""),
    [busy, setBusy] = useState(false),
    [menu, setMenu] = useState(false),
    [url, setUrl] = useState(() => new URL(window.location.href));
  const generation = useRef({ session: 0, view: 0 });
  const readController = useRef<AbortController | null>(null);
  const bootController = useRef<AbortController | null>(null);
  const retryAttempts = useRef(
    new Map<string, { key: string; version: number }>(),
  );
  const onboard = url.searchParams.get("view") === "onboard";
  const selectedId = url.searchParams.get("company");
  const recommending = url.searchParams.get("view") === "recommendations";
  const captureScope = () => ({ ...generation.current });
  const isCurrent = (scope: { session: number; view: number }) =>
    scope.session === generation.current.session &&
    scope.view === generation.current.view;

  function invalidateView() {
    generation.current.view += 1;
    readController.current?.abort();
    readController.current = null;
    setBusy(false);
    setLoading(false);
  }
  function changeAccount(nextUser: User | null) {
    generation.current.session += 1;
    bootController.current?.abort();
    bootController.current = null;
    invalidateView();
    retryAttempts.current.clear();
    setUser(nextUser);
    setCompanies([]);
    setFixtures([]);
    setConsents([]);
    setData(null);
    setLoadError("");
    setActionError("");
    setMenu(false);
    if (!nextUser) {
      const next = new URL(window.location.href);
      next.search = "";
      window.history.replaceState({}, "", next);
      setUrl(next);
    }
  }
  function changeView(next: URL) {
    invalidateView();
    setData(null);
    setLoadError("");
    setActionError("");
    setLoading(true);
    setUrl(next);
    setMenu(false);
  }
  function navigate(id?: string, view?: string) {
    const next = new URL(window.location.href);
    next.search = "";
    if (id) next.searchParams.set("company", id);
    if (view) next.searchParams.set("view", view);
    window.history.pushState({}, "", next);
    changeView(next);
  }
  useEffect(() => {
    const fn = () => changeView(new URL(window.location.href));
    window.addEventListener("popstate", fn);
    return () => window.removeEventListener("popstate", fn);
  }, []);
  async function boot() {
    const scope = captureScope();
    const controller = new AbortController();
    // Identity restoration belongs to the session, independent of company history.
    bootController.current?.abort();
    bootController.current = controller;
    const active = () =>
      scope.session === generation.current.session &&
      !controller.signal.aborted;
    setBooting(true);
    setBootError("");
    try {
      const result = await api.me(controller.signal);
      if (!active()) return;
      changeAccount(result.user);
      setBooting(false);
    } catch (e) {
      if (!active()) return;
      if (e instanceof ApiError && e.status === 401) changeAccount(null);
      else setBootError(message(e));
      setBooting(false);
    }
  }
  useEffect(() => {
    void boot();
    return () => bootController.current?.abort();
  }, []);
  async function loadWorkspace() {
    if (!user || user.role !== "CLIENT") return;
    const scope = captureScope();
    const controller = new AbortController();
    readController.current?.abort();
    readController.current = controller;
    const active = () => isCurrent(scope) && !controller.signal.aborted;
    setLoading(true);
    setLoadError("");
    try {
      const [list, fs, cs] = await Promise.all([
        api.companies(controller.signal),
        api.fixtures(controller.signal).catch((e) => {
          if (e instanceof ApiError && e.status === 404)
            return { items: [] as Fixture[], total: 0 };
          throw e;
        }),
        api.consents(controller.signal),
      ]);
      if (!active()) return;
      const id = selectedId ?? (!onboard ? list.items[0]?.id : undefined);
      const result = id ? await api.company(id, controller.signal) : null;
      if (!active()) return;
      setCompanies(list.items);
      setFixtures(fs.items);
      setConsents(cs.items);
      setData(result);
    } catch (e) {
      if (!active()) return;
      if (e instanceof ApiError && e.status === 401) changeAccount(null);
      else setLoadError(message(e));
    } finally {
      if (active()) setLoading(false);
    }
  }
  useEffect(() => {
    void loadWorkspace();
    return () => readController.current?.abort();
  }, [user, url]);
  async function logout() {
    // Logout belongs to the session even if navigation happens while it completes.
    invalidateView();
    const scope = captureScope();
    setBusy(true);
    setActionError("");
    try {
      await api.logout();
      if (scope.session === generation.current.session) changeAccount(null);
    } catch (e) {
      if (isCurrent(scope)) setActionError(message(e));
    } finally {
      if (isCurrent(scope)) setBusy(false);
    }
  }
  async function addCompany(inn: string) {
    const scope = captureScope();
    setBusy(true);
    setActionError("");
    try {
      const result = await api.onboard(inn, consents);
      if (!isCurrent(scope)) return;
      navigate(result.company.id);
    } catch (e) {
      if (!isCurrent(scope)) return;
      if (e instanceof ApiError && e.status === 401) changeAccount(null);
      else setActionError(message(e));
    } finally {
      if (isCurrent(scope)) setBusy(false);
    }
  }
  async function retry() {
    if (!data) return;
    const scope = captureScope();
    const companyId = data.company.id;
    // A lost response may have committed. Keep both body revision and key with its
    // original company across navigation so a later retry replays that command.
    const attempt = retryAttempts.current.get(companyId) ?? {
      key: crypto.randomUUID(),
      version: data.company.version,
    };
    retryAttempts.current.set(companyId, attempt);
    setBusy(true);
    setActionError("");
    try {
      const result = await api.retry(companyId, attempt.version, attempt.key);
      if (
        scope.session === generation.current.session &&
        retryAttempts.current.get(companyId) === attempt
      )
        retryAttempts.current.delete(companyId);
      if (isCurrent(scope)) setData(result);
    } catch (e) {
      if (!isCurrent(scope)) return;
      if (e instanceof ApiError && e.status === 401) changeAccount(null);
      else setActionError(message(e));
    } finally {
      if (isCurrent(scope)) setBusy(false);
    }
  }
  if (booting)
    return (
      <div className="boot">
        <Brand />
        <Loading />
      </div>
    );
  if (bootError)
    return (
      <div className="boot">
        <Brand />
        <ErrorNotice error={bootError} onRetry={() => void boot()} />
      </div>
    );
  if (!user) return <Auth onAuth={changeAccount} />;
  return (
    <div className="workspace">
      <aside className={"sidebar " + (menu ? "open" : "")}>
        <Brand />
        <div className="nav-label">Рабочее пространство</div>
        <nav>
          <button
            className={!onboard ? "active" : ""}
            onClick={() => navigate()}
          >
            <Icon name="building" />
            {user.role === "CLIENT" ? "Мои компании" : "Кабинет специалиста"}
            {user.role === "CLIENT" && (
              <span className="nav-count">{companies.length}</span>
            )}
          </button>
          {user.role === "CLIENT" && (
            <button
              className={onboard ? "active" : ""}
              onClick={() => navigate(undefined, "onboard")}
            >
              <Icon name="plus" />
              Добавить компанию
            </button>
          )}
        </nav>
        <div className="sidebar-note">
          <span className="small-red-dot" /> Демонстрационный сервис
          <p>Реестр, обороты и проверки — локальные имитации.</p>
        </div>
        <div className="account">
          <span className="avatar">
            {user.display_name.slice(0, 1).toUpperCase()}
          </span>
          <div>
            <strong>{user.display_name}</strong>
            <small>
              {user.role === "CLIENT"
                ? "Клиент · демо"
                : "Кредитный специалист"}
            </small>
          </div>
          <button
            aria-label="Выйти из аккаунта"
            title="Выйти"
            onClick={() => void logout()}
            disabled={busy}
          >
            <Icon name="logout" />
          </button>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="topbar">
          <button
            className="mobile-menu icon-button"
            aria-label="Открыть меню"
            aria-expanded={menu}
            onClick={() => setMenu(!menu)}
          >
            <Icon name="menu" />
          </button>
          <span className="breadcrumbs">
            Бизнес <span>/</span>{" "}
            {onboard
              ? "Новая компания"
              : user.role === "CLIENT"
                ? "Мои компании"
                : "Специалист"}
          </span>
          <div className="topbar-right">
            <DemoBadge />
            <span className="account-email">{user.email}</span>
          </div>
        </header>
        <main className="main-content">
          {user.role === "CREDIT_OFFICER" ? (
            <>
              <div className="page-heading">
                <div className="eyebrow accent">Кабинет специалиста</div>
                <h1>Доступ подтверждён</h1>
                <p>
                  Вы вошли как кредитный специалист демонстрационного сервиса.
                </p>
              </div>
              <section className="card officer-card">
                <span className="large-icon">
                  <Icon name="shield" size={32} />
                </span>
                <h2>{user.display_name}</h2>
                <p>
                  Роль кредитного специалиста назначена сервером через
                  демо-инструменты.
                </p>
                <dl>
                  <div>
                    <dt>Аккаунт</dt>
                    <dd>{user.email}</dd>
                  </div>
                  <div>
                    <dt>Роль</dt>
                    <dd>CREDIT_OFFICER</dd>
                  </div>
                </dl>
                <div className="notice quiet">
                  <Icon name="info" />
                  <span>
                    Данные клиентских компаний защищены. Для проверки
                    клиентского маршрута войдите под демо-клиентом.
                  </span>
                </div>
              </section>
              {actionError && <ErrorNotice error={actionError} />}
            </>
          ) : loading ? (
            <Loading />
          ) : loadError ? (
            <ErrorNotice
              error={loadError}
              onRetry={() => void loadWorkspace()}
            />
          ) : onboard ? (
            <Onboarding
              fixtures={fixtures}
              consents={consents}
              busy={busy}
              onSubmit={(inn) => void addCompany(inn)}
              onCancel={() => navigate()}
              error={actionError}
            />
          ) : (
            <>
              {companies.length > 0 && (
                <div className="company-switcher">
                  <label htmlFor="company-select">Ваша компания</label>
                  <select
                    id="company-select"
                    value={data?.company.id ?? ""}
                    onChange={(e) => navigate(e.target.value)}
                  >
                    {companies.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name} · {c.inn}
                      </option>
                    ))}
                  </select>
                  <button
                    className="button secondary"
                    onClick={() => navigate(undefined, "onboard")}
                  >
                    <Icon name="plus" size={17} />
                    Добавить
                  </button>
                </div>
              )}
              {data && recommending ? (
                <Recommendations
                  key={`${user.id}:${data.company.id}:${data.precheck.id}`}
                  data={data}
                  onBack={() => navigate(data.company.id)}
                />
              ) : data ? (
                <CompanyDetail
                  data={data}
                  busy={busy}
                  error={actionError}
                  onRecommend={() =>
                    navigate(data.company.id, "recommendations")
                  }
                  onRetry={() => void retry()}
                />
              ) : (
                <>
                  <div className="page-heading">
                    <div className="eyebrow accent">
                      Ваш бизнес — точка отсчёта
                    </div>
                    <h1>Добро пожаловать, {user.display_name}</h1>
                    <p>
                      Добавьте компанию, чтобы увидеть её сведения и результаты
                      проверки.
                    </p>
                  </div>
                  <section className="card empty-state">
                    <span className="large-icon">
                      <Icon name="building" size={34} />
                    </span>
                    <h2>Здесь появятся ваши компании</h2>
                    <p>
                      Понадобится только ИНН и согласие на проверку
                      синтетических сведений. Начните с одного из готовых
                      демо-профилей.
                    </p>
                    <button
                      className="button primary"
                      onClick={() => navigate(undefined, "onboard")}
                    >
                      Добавить компанию
                      <Icon />
                    </button>
                    <div className="empty-features">
                      <span>
                        <Icon name="check" size={16} />
                        ИП и ООО
                      </span>
                      <span>
                        <Icon name="check" size={16} />
                        Сохранение данных
                      </span>
                      <span>
                        <Icon name="shield" size={16} />
                        Без запроса БКИ
                      </span>
                    </div>
                  </section>
                  {actionError && <ErrorNotice error={actionError} />}
                </>
              )}
            </>
          )}
          <footer className="workspace-footer">
            <span>Кредитный маршрут · 2026</span>
            <span>Только синтетические данные</span>
          </footer>
        </main>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
