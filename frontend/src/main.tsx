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
import { Brand, Icon, Loading, ErrorNotice } from "./components";
import { Auth } from "./features/identity/Auth";
import { Onboarding } from "./features/companies/Onboarding";
import { CompanyDetail } from "./features/companies/CompanyDetail";
import { Recommendations } from "./features/recommendations/Recommendations";
import {
  ApplicationPage,
  LeaveGuard,
} from "./features/applications/ApplicationPage";
import { MyApplications } from "./features/applications/MyApplications";
import {
  CommandAttempts,
  outcomeUnknown,
} from "./features/applications/commands";
import { handoffIdOf } from "./features/documents/HandoffAction";
import { HandoffPage } from "./features/documents/HandoffPage";
import { NoAccess } from "./features/officer/NoAccess";
import {
  OfficerQueue,
  queueParams,
  readQueueFilters,
} from "./features/officer/OfficerQueue";
import { QueueFilters } from "./features/officer/officerApi";
import { ReviewPage } from "./features/officer/ReviewPage";
import { Tour } from "./features/tour/Tour";
import { useTour } from "./features/tour/useTour";
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
  // Application command keys, kept per session across navigation like the company retry above.
  const commandAttempts = useRef<CommandAttempts>(new Map());
  // An open questionnaire may hold unsaved edits: every way out (links, history, logout) asks it first.
  const leaveGuard = useRef<LeaveGuard | null>(null);
  const leaving = useRef(false);
  const shownUrl = useRef(window.location.href);
  // The officer's last queue filters, so the way back from a review returns to the same list.
  const lastQueue = useRef<QueueFilters>({});
  // The client walkthrough: opens by itself on a first visit, again from «Как это работает».
  const tour = useTour(user);
  const onboard = url.searchParams.get("view") === "onboard";
  const selectedId = url.searchParams.get("company");
  const recommending = url.searchParams.get("view") === "recommendations";
  const applicationList = url.searchParams.get("view") === "applications";
  const applicationId = url.searchParams.get("application");
  // The one pathname route: the local Alfa-Business hand-off page of an approved application.
  const handoffId = handoffIdOf(url.pathname);
  const inApplications = applicationList || !!applicationId || !!handoffId;
  const queueView = url.searchParams.get("view") === "queue";
  const officer = user?.role === "CREDIT_OFFICER";
  // The officer's pages: the queue (also the bare address) and a review opened from it; every other address is refused.
  const officerHome = officer && !handoffId && (queueView || !url.search || !!applicationId);
  useEffect(() => {
    if (officer && queueView)
      lastQueue.current = readQueueFilters(url.searchParams);
  }, [url, officer]);
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
    commandAttempts.current.clear();
    lastQueue.current = {};
    leaving.current = false;
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
      next.pathname = "/";
      next.search = "";
      window.history.replaceState({}, "", next);
      shownUrl.current = next.href;
      setUrl(next);
    }
  }
  function changeView(next: URL) {
    invalidateView();
    shownUrl.current = next.href;
    setData(null);
    setLoadError("");
    setActionError("");
    setLoading(true);
    setUrl(next);
    setMenu(false);
  }
  /** Runs `proceed` once the open questionnaire has saved its edits or the customer chose to leave. */
  function afterLeaving(proceed: () => void, stay: () => void = () => {}) {
    const guard = leaveGuard.current;
    if (!guard) return proceed();
    if (leaving.current) return stay();
    leaving.current = true;
    void guard().then((ok) => {
      leaving.current = false;
      if (ok) proceed();
      else stay();
    });
  }
  function navigate(
    id?: string,
    view?: string,
    application?: string,
    params: Record<string, string> = {},
  ) {
    const next = new URL(window.location.href);
    next.pathname = "/";
    next.search = "";
    if (id) next.searchParams.set("company", id);
    if (view) next.searchParams.set("view", view);
    if (application) next.searchParams.set("application", application);
    for (const [name, value] of Object.entries(params))
      next.searchParams.set(name, value);
    afterLeaving(() => {
      window.history.pushState({}, "", next);
      changeView(next);
    });
  }
  /** Opens an in-app path (the hand-off page) through the same leave guard as `navigate`. */
  function openPath(path: string) {
    const next = new URL(path, window.location.origin);
    afterLeaving(() => {
      window.history.pushState({}, "", next);
      changeView(next);
    });
  }
  useEffect(() => {
    const fn = () => {
      const next = new URL(window.location.href);
      // The browser has already moved; staying in the questionnaire puts its address back.
      afterLeaving(
        () => changeView(next),
        () => window.history.pushState({}, "", shownUrl.current),
      );
    };
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
      const id =
        selectedId ??
        (!onboard && !inApplications && !queueView
          ? list.items[0]?.id
          : undefined);
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
  async function addCompany(inn: string, verificationId: string) {
    const scope = captureScope();
    setBusy(true);
    setActionError("");
    try {
      const result = await api.onboard(inn, consents, verificationId);
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
    // original company across navigation so a later retry replays that command; an
    // answer (a success, or a refusal that recorded nothing) releases them.
    const attempt = retryAttempts.current.get(companyId) ?? {
      key: crypto.randomUUID(),
      version: data.company.version,
    };
    retryAttempts.current.set(companyId, attempt);
    const release = () => {
      if (
        scope.session === generation.current.session &&
        retryAttempts.current.get(companyId) === attempt
      )
        retryAttempts.current.delete(companyId);
    };
    setBusy(true);
    setActionError("");
    try {
      const result = await api.retry(companyId, attempt.version, attempt.key);
      release();
      if (isCurrent(scope)) setData(result);
    } catch (e) {
      if (!outcomeUnknown(e)) release();
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
          {officer && (
            <button
              className={officerHome ? "active" : ""}
              onClick={() => navigate(undefined, "queue")}
            >
              <Icon name="file" />
              Очередь заявок
            </button>
          )}
          {user.role === "CLIENT" && (
            <button
              className={
                !onboard && !inApplications && !queueView ? "active" : ""
              }
              onClick={() => navigate()}
            >
              <Icon name="building" />
              Мои компании
              <span className="nav-count">{companies.length}</span>
            </button>
          )}
          {user.role === "CLIENT" && (
            <button
              className={inApplications ? "active" : ""}
              onClick={() => navigate(undefined, "applications")}
            >
              <Icon name="file" />
              Мои заявки
            </button>
          )}
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
          <span className="small-red-dot" /> Финансирование для ИП&nbsp;и&nbsp;ООО
          <p>
            Сведения о компании — из реестра и открытых источников, кредитная
            история — только с согласия клиента.
          </p>
        </div>
        <div className="account">
          <span className="avatar">
            {user.display_name.slice(0, 1).toUpperCase()}
          </span>
          <div>
            <strong>{user.display_name}</strong>
            <small>
              {user.role === "CLIENT" ? "Клиент" : "Кредитный специалист"}
            </small>
          </div>
          <button
            aria-label="Выйти из аккаунта"
            title="Выйти"
            onClick={() => afterLeaving(() => void logout())}
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
            Бизнес <span aria-hidden="true">/</span>{" "}
            {handoffId
              ? "Альфа-Бизнес"
              : officer
                ? applicationId
                  ? "Рассмотрение заявки"
                  : "Очередь заявок"
                : onboard
                  ? "Новая компания"
                  : inApplications
                    ? "Мои заявки"
                    : "Мои компании"}
          </span>
          <div className="topbar-right">
            {tour.enabled && (
              <button
                ref={tour.trigger}
                type="button"
                className="button secondary tour-trigger"
                onClick={() => tour.restart()}
              >
                <Icon name="help" size={18} />
                <span>Как это работает</span>
              </button>
            )}
            <span className="account-email">{user.email}</span>
          </div>
        </header>
        <main className="main-content">
          {officer && actionError && <ErrorNotice error={actionError} />}
          {officer ? (
            handoffId ? (
              <NoAccess
                text="Страница перехода в Альфа-Бизнес открывается только владельцу одобренной заявки."
                action="Перейти к очереди заявок"
                onAction={() => navigate(undefined, "queue")}
              />
            ) : applicationId ? (
              <ReviewPage
                key={`${user.id}:${applicationId}`}
                applicationId={applicationId}
                userId={user.id}
                attempts={commandAttempts.current}
                onOpenQueue={() =>
                  navigate(
                    undefined,
                    "queue",
                    undefined,
                    queueParams(lastQueue.current),
                  )
                }
                onUnauthorized={() => changeAccount(null)}
              />
            ) : queueView || !url.search ? (
              <OfficerQueue
                key={user.id}
                userId={user.id}
                filters={readQueueFilters(url.searchParams)}
                onFilter={(filters) =>
                  navigate(undefined, "queue", undefined, queueParams(filters))
                }
                onOpen={(id) => navigate(undefined, undefined, id)}
                onUnauthorized={() => changeAccount(null)}
              />
            ) : (
              <NoAccess
                text="Этот раздел доступен только клиентам: компании, подбор и анкеты ведут сами клиенты. Отправленные заявки — в очереди."
                action="Перейти к очереди заявок"
                onAction={() => navigate(undefined, "queue")}
              />
            )
          ) : queueView ? (
            <NoAccess
              text="Очередь заявок доступна только кредитным специалистам. Ваши заявки и их статус — в разделе «Мои заявки»."
              action="Перейти к моим заявкам"
              onAction={() => navigate(undefined, "applications")}
            />
          ) : loading ? (
            <Loading />
          ) : loadError ? (
            <ErrorNotice
              error={loadError}
              onRetry={() => void loadWorkspace()}
            />
          ) : handoffId ? (
            <HandoffPage
              key={`${user.id}:${handoffId}`}
              applicationId={handoffId}
              onOpenApplication={(id) => navigate(undefined, undefined, id)}
              onOpenList={() => navigate(undefined, "applications")}
              onUnauthorized={() => changeAccount(null)}
            />
          ) : applicationId ? (
            <ApplicationPage
              key={`${user.id}:${applicationId}`}
              applicationId={applicationId}
              attempts={commandAttempts.current}
              onOpenList={() => navigate(undefined, "applications")}
              onOpenApplication={(id) => navigate(undefined, undefined, id)}
              onRecommend={(companyId) =>
                navigate(companyId, "recommendations")
              }
              onOpenHandoff={openPath}
              onLeaveGuard={(guard) => {
                leaveGuard.current = guard;
              }}
              onUnauthorized={() => changeAccount(null)}
            />
          ) : applicationList ? (
            <MyApplications
              key={user.id}
              onOpen={(id) => navigate(undefined, undefined, id)}
              onRecommend={() =>
                companies[0]
                  ? navigate(companies[0].id, "recommendations")
                  : navigate(undefined, "onboard")
              }
              onUnauthorized={() => changeAccount(null)}
            />
          ) : onboard ? (
            <Onboarding
              fixtures={fixtures}
              consents={consents}
              busy={busy}
              onSubmit={(inn, verificationId) =>
                void addCompany(inn, verificationId)
              }
              onCancel={() => navigate()}
              onUnauthorized={() => changeAccount(null)}
              error={actionError}
              onClearError={() => setActionError("")}
            />
          ) : (
            <>
              {/* The product choice keeps the amount as its only input: switching companies is on the profile. */}
              {companies.length > 0 && !(data && recommending) && (
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
                  attempts={commandAttempts.current}
                  onApplicationCreated={(id) =>
                    navigate(undefined, undefined, id)
                  }
                  onUnauthorized={() => changeAccount(null)}
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
                      Понадобится ИНН, подтверждение полномочий через Госуслуги
                      и согласие на проверку сведений компании.
                    </p>
                    <button
                      className="button primary"
                      data-tour="add-company"
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
        <Tour tour={tour} route={url.href} onEmptyPage={() => navigate()} />
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
