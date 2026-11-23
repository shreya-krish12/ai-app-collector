import type { ReactNode } from 'react';

export function Panel({
  title, subtitle, actions, span = 12, children, flush = false,
}: {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  span?: 3 | 4 | 5 | 6 | 7 | 8 | 12;
  children: ReactNode;
  flush?: boolean;
}) {
  return (
    <section className={`panel span-${span}`}>
      {(title || actions) && (
        <header className="panel-head">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p className="muted">{subtitle}</p>}
          </div>
          {actions && <div className="panel-actions">{actions}</div>}
        </header>
      )}
      <div className={flush ? 'panel-body flush' : 'panel-body'}>{children}</div>
    </section>
  );
}

export function Kpi({ label, value, note, tone = 'ink' }: {
  label: string; value: ReactNode; note?: string; tone?: 'ink' | 'red';
}) {
  return (
    <div className={`kpi kpi-${tone}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {note && <div className="kpi-note">{note}</div>}
    </div>
  );
}

export function StatusPill({ status }: { status: string }) {
  const red = ['unsanctioned', 'failed', 'error', 'partial'].includes(status);
  const solid = ['running'].includes(status);
  return <span className={`pill ${red ? 'pill-red' : solid ? 'pill-solid' : 'pill-ink'}`}>{status}</span>;
}

export function EmptyState({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      {body && <p className="muted">{body}</p>}
      {action}
    </div>
  );
}

export function SkeletonRows({ rows = 6, cols }: { rows?: number; cols: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, r) => (
        <tr key={r} className="skeleton-row">
          {Array.from({ length: cols }).map((__, c) => (
            <td key={c}><span className="skeleton" /></td>
          ))}
        </tr>
      ))}
    </>
  );
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="banner-error" role="alert">{message}</div>;
}

export function Bar({ value, max, tone = 'ink' }: { value: number; max: number; tone?: 'ink' | 'red' }) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div className="bar-track" aria-hidden>
      <div className={`bar-fill bar-${tone}`} style={{ width: `${pct}%` }} />
    </div>
  );
}
