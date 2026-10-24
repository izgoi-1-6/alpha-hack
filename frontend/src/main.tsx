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
  const retryKey = useRef<string | null>(null);
  const onboard = url.searchParams.get("view") === "onboard";
  const selectedId = url.searchParams.get("company");
  function navigate(id?: string, view?: string) {
    const next = new URL(window.location.href);
    next.search = "";
    if (id) next.searchParams.set("company", id);
    if (view) next.searchParams.set("view", view);
    window.history.pushState({}, "", next);
    setUrl(next);
    setMenu(false);
    setActionError("");
    retryKey.current = null;
  }
  useEffect(() => {
    const fn = () => setUrl(new URL(window.location.href));
    window.addEventListener("popstate", fn);
    return () => window.removeEventListener("popstate", fn);
  }, []);
  async function boot() {
    setBooting(true);
    setBootError("");
    try {
      setUser((await api.me()).user);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setUser(null);
      else setBootError(message(e));
    } finally {
      setBooting(false);
    }
  }
  useEffect(() => {
    void boot();
  }, []);
  function handleError(e: unknown) {
    if (e instanceof ApiError && e.status === 401) {
      setUser(null);
      setLoadError("");
    } else setLoadError(message(e));
  }
  async function loadWorkspace() {
    if (!user || user.role !== "CLIENT") return;
    setLoading(true);
    setLoadError("");
    try {
      const [list, fs, cs] = await Promise.all([
        api.companies(),
        api.fixtures().catch((e) => {
          if (e instanceof ApiError && e.status === 404)
            return { items: [] as Fixture[], total: 0 };
          throw e;
        }),
        api.consents(),
      ]);
      setCompanies(list.items);
      setFixtures(fs.items);
      setConsents(cs.items);
      const id = selectedId ?? (!onboard ? list.items[0]?.id : undefined);
      if (id) setData(await api.company(id));
      else setData(null);
    } catch (e) {
      handleError(e);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void loadWorkspace();
  }, [user, selectedId, onboard]);
  async function logout() {
    setBusy(true);
    setActionError("");
    try {
      await api.logout();
      setUser(null);
      setData(null);
      navigate();
    } catch (e) {
      setActionError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function addCompany(inn: string) {
    setBusy(true);
    setActionError("");
    try {
      const r = await api.onboard(inn, consents);
      setData(r);
      navigate(r.company.id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setUser(null);
      else setActionError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function retry() {
    if (!data) return;
    setBusy(true);
    setActionError("");
    retryKey.current ??= crypto.randomUUID();
    try {
      setData(
        await api.retry(
          data.company.id,
          data.company.version,
          retryKey.current,
        ),
      );
      retryKey.current = null;
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setUser(null);
      else setActionError(message(e));
    } finally {
      setBusy(false);
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
  if (!user)
    return (
      <Auth
        onAuth={(u) => {
          setUser(u);
          setActionError("");
        }}
      />
    );
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
              {data ? (
                <CompanyDetail
                  data={data}
                  busy={busy}
                  error={actionError}
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
