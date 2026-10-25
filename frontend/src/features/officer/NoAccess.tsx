import { Icon } from "../../components";

/**
 * A destination of the other role. The server refuses such reads anyway (403); the shell says so plainly instead of
 * rendering an empty or broken screen, and points back to the session role's own workspace.
 */
export function NoAccess({
  text,
  action,
  onAction,
}: {
  text: string;
  action: string;
  onAction: () => void;
}) {
  return (
    <>
      <div className="page-heading">
        <div className="eyebrow accent">Раздел недоступен</div>
        <h1>Нет доступа</h1>
        <p>{text}</p>
      </div>
      <section className="card empty-state">
        <span className="large-icon">
          <Icon name="shield" size={34} />
        </span>
        <h2>Этот раздел для другой роли</h2>
        <p>
          Права проверяет сервер: данные другой роли не загружаются и не
          показываются.
        </p>
        <button type="button" className="button primary" onClick={onAction}>
          {action}
          <Icon />
        </button>
      </section>
    </>
  );
}
