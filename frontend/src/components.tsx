import React from "react";
export function Icon({
  name = "arrow",
  size = 20,
}: {
  name?: string;
  size?: number;
}) {
  const paths: Record<string, React.ReactNode> = {
    arrow: (
      <>
        <path d="M5 12h14M13 6l6 6-6 6" />
      </>
    ),
    route: (
      <>
        <path d="M6 18v-5a3 3 0 0 1 3-3h6a3 3 0 0 0 3-3V4M14 4h4v4" />
        <circle cx="6" cy="18" r="2" />
      </>
    ),
    building: (
      <>
        <path d="M4 21V5l8-3v19M12 8h8v13M2 21h20M7 7h2M7 11h2M7 15h2M15 11h2M15 15h2" />
      </>
    ),
    plus: <path d="M12 5v14M5 12h14" />,
    check: <path d="m5 12 4 4L19 6" />,
    shield: (
      <>
        <path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Z" />
        <path d="m8 12 3 3 5-6" />
      </>
    ),
    logout: (
      <>
        <path d="M10 4H4v16h6M14 8l4 4-4 4M8 12h10" />
      </>
    ),
    refresh: (
      <>
        <path d="M20 7v5h-5M4 17v-5h5" />
        <path d="M6 7a7 7 0 0 1 12-1l2 6M4 12l2 6a7 7 0 0 0 12-1" />
      </>
    ),
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
    file: (
      <>
        <path d="M7 3h7l5 5v13H7z" />
        <path d="M14 3v5h5M10 13h6M10 17h6" />
      </>
    ),
    info: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 11v6M12 7h.01" />
      </>
    ),
    download: <path d="M12 4v11M7 10l5 5 5-5M5 20h14" />,
    upload: <path d="M12 16V5M7 10l5-5 5 5M5 20h14" />,
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] ?? paths.arrow}
    </svg>
  );
}
export function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark">
        <Icon name="route" size={25} />
      </span>
      <span>
        Кредитный
        <br />
        маршрут<span className="brand-caption">Финансирование бизнеса</span>
      </span>
    </div>
  );
}
export function DemoBadge({ label = "Демо · имитация" }: { label?: string }) {
  return (
    <span className="demo-badge">
      <span />
      {label}
    </span>
  );
}
export function ErrorNotice({
  error,
  onRetry,
}: {
  error: string;
  onRetry?: () => void;
}) {
  return (
    <div className="notice error" role="alert">
      <Icon name="info" />
      <div>
        {error}
        {onRetry && (
          <button className="text-button" onClick={onRetry}>
            Повторить попытку <Icon name="refresh" size={15} />
          </button>
        )}
      </div>
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading" role="status">
      <span className="spinner" />
      Загружаем данные…
    </div>
  );
}
