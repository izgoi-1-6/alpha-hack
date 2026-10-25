import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  Application,
  applicationsApi,
  ConsentDocument,
  Dialog,
  errorMessage,
  HistoryItem,
} from "../../api";
import { ErrorNotice, Icon, Loading } from "../../components";
import { CancelAction } from "./CancelAction";
import { CommandAttempts } from "./commands";
import { productName } from "./format";
import { StatusView } from "./StatusView";
import { LeaveGuard, Wizard } from "./Wizard";
export type { LeaveGuard } from "./Wizard";
import "./applications.css";

type Loaded =
  | {
      kind: "draft";
      application: Application;
      dialog: Dialog;
      consents: ConsentDocument[];
    }
  | { kind: "status"; application: Application; history: HistoryItem[] }
  /** A draft whose product policy was withdrawn: the dialog answers 409 RECOMMENDATION_STALE. */
  | { kind: "stale"; application: Application };

/**
 * `?application=<id>`: the wizard while the application is a DRAFT, its status and timeline otherwise. Reads are
 * revisioned and aborted when superseded, so a late response never replaces a newer view of the application.
 */
export function ApplicationPage({
  applicationId,
  attempts,
  onOpenList,
  onOpenApplication,
  onRecommend,
  onLeaveGuard,
  onUnauthorized,
}: {
  applicationId: string;
  attempts: CommandAttempts;
  onOpenList: () => void;
  onOpenApplication: (id: string) => void;
  onRecommend: (companyId: string) => void;
  /** The wizard registers how to leave it; the App consults it before any navigation. */
  onLeaveGuard: (guard: LeaveGuard | null) => void;
  onUnauthorized: () => void;
}) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [failure, setFailure] = useState<{
    notFound: boolean;
    message: string;
  } | null>(null);
  const [notice, setNotice] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const [submittedHere, setSubmittedHere] = useState(false);
  const revision = useRef(0);
  const reader = useRef<AbortController | null>(null);
  const consents = useRef<ConsentDocument[] | null>(null);
  const shown = useRef<Loaded | null>(null);
  useEffect(() => {
    void load();
    return () => {
      revision.current += 1;
      reader.current?.abort();
    };
  }, []);

  async function read(signal: AbortSignal): Promise<Loaded> {
    const { application } = await applicationsApi.get(applicationId, signal);
    if (application.status !== "DRAFT") {
      const { items } = await applicationsApi.history(applicationId, signal);
      return { kind: "status", application, history: items };
    }
    try {
      const [dialog, documents] = await Promise.all([
        applicationsApi.dialog(applicationId, signal),
        consents.current ??
          applicationsApi.consents(signal).then((result) => result.items),
      ]);
      consents.current = documents;
      return { kind: "draft", application, dialog, consents: documents };
    } catch (error) {
      if (error instanceof ApiError && error.code === "RECOMMENDATION_STALE")
        return { kind: "stale", application };
      throw error;
    }
  }

  /** Reloads; `statusNotice` explains a draft that turned out to be submitted or cancelled elsewhere. */
  async function load(statusNotice?: string): Promise<Loaded | null> {
    const mine = ++revision.current;
    reader.current?.abort();
    const controller = new AbortController();
    reader.current = controller;
    const current = () =>
      mine === revision.current && !controller.signal.aborted;
    try {
      const next = await read(controller.signal);
      if (!current()) return null;
      const leftDraft =
        shown.current?.kind === "draft" && next.kind === "status";
      if (leftDraft) setSubmittedHere(true);
      setNotice(leftDraft && statusNotice ? statusNotice : "");
      shown.current = next;
      setLoaded(next);
      setFailure(null);
      return next;
    } catch (error) {
      if (!current()) return null;
      if (error instanceof ApiError && error.status === 401) {
        onUnauthorized();
        return null;
      }
      const message = errorMessage(error);
      if (shown.current) setNotice(`Не удалось обновить заявку. ${message}`);
      else
        setFailure({
          notFound: error instanceof ApiError && error.status === 404,
          message,
        });
      return null;
    }
  }

  function announce(text: string) {
    // Clear first so that the same message is announced again.
    setAnnouncement("");
    window.requestAnimationFrame(() => setAnnouncement(text));
  }

  let content;
  if (failure)
    content = failure.notFound ? (
      <>
        <div className="page-heading">
          <div className="eyebrow accent">Мои заявки</div>
          <h1>Заявка не найдена</h1>
          <p>Ссылка устарела или заявка принадлежит другому клиенту.</p>
        </div>
        <button type="button" className="button primary" onClick={onOpenList}>
          Перейти к моим заявкам
          <Icon />
        </button>
      </>
    ) : (
      <ErrorNotice error={failure.message} onRetry={() => void load()} />
    );
  else if (!loaded) content = <Loading />;
  else if (loaded.kind === "draft")
    content = (
      <Wizard
        application={loaded.application}
        dialog={loaded.dialog}
        consents={loaded.consents}
        attempts={attempts}
        refresh={async (statusNotice) => {
          const next = await load(statusNotice);
          return next?.kind === "draft" ? next.dialog : null;
        }}
        announce={announce}
        onOpenList={onOpenList}
        onOpenApplication={onOpenApplication}
        onRecalculate={onRecommend}
        registerLeaveGuard={onLeaveGuard}
        onUnauthorized={onUnauthorized}
      />
    );
  else if (loaded.kind === "status")
    content = (
      <StatusView
        application={loaded.application}
        history={loaded.history}
        attempts={attempts}
        reload={() => load()}
        announce={announce}
        focusOnMount={submittedHere}
        onOpenList={onOpenList}
        onRecommend={onRecommend}
        onUnauthorized={onUnauthorized}
      />
    );
  else
    content = (
      <div className="status-page">
        <button type="button" className="back-button" onClick={onOpenList}>
          ← Мои заявки
        </button>
        <div className="page-heading">
          <div className="eyebrow accent">
            Анкета · {productName(loaded.application)}
          </div>
          <h1>Условия продукта изменились</h1>
          <p>{loaded.application.company.name}</p>
        </div>
        <div className="notice caution">
          <Icon name="info" />
          <span>
            Продукт больше не предлагается на прежних условиях, поэтому анкету
            нельзя продолжить. Пересчитайте оценку и начните анкету заново; этот
            черновик можно отменить.
          </span>
        </div>
        <div className="status-actions">
          <button
            type="button"
            className="button primary"
            onClick={() => onRecommend(loaded.application.company_id)}
          >
            <Icon name="refresh" size={17} />
            Пересчитать оценку
          </button>
          {loaded.application.allowed_actions.includes("cancel") && (
            <CancelAction
              application={loaded.application}
              attempts={attempts}
              reload={() => load()}
              announce={announce}
              onUnauthorized={onUnauthorized}
            />
          )}
        </div>
      </div>
    );

  return (
    <div className="application-page">
      <div
        className="sr-only application-live"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {announcement}
      </div>
      {notice && (
        <div className="notice caution" role="status">
          <Icon name="info" />
          <span>{notice}</span>
        </div>
      )}
      {content}
    </div>
  );
}
