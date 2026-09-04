import type { ReactNode } from 'react';
import { CheckCircle, Info, Warning, WarningOctagon } from '@phosphor-icons/react/dist/ssr';

/** A framed region. Used only where elevation carries real hierarchy. */
export function Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <section className={`overflow-hidden rounded border border-line bg-surface ${className}`}>
      {children}
    </section>
  );
}

export function PanelHead({ title, meta, actions }: {
  title: string; meta?: ReactNode; actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line px-3.5 py-2.5">
      <h2 className="text-[13px] font-medium tracking-tight">{title}</h2>
      {meta && <div className="text-[12px] text-muted">{meta}</div>}
      {actions && <div className="ml-auto flex items-center gap-1.5">{actions}</div>}
    </header>
  );
}

/**
 * A single headline figure. A number this important is not a chart -- it is a
 * number, set large, with its unit and context beside it.
 */
export function Stat({ label, value, unit, hint, tone = 'neutral' }: {
  label: string; value: string; unit?: string; hint?: string;
  tone?: 'neutral' | 'good' | 'warning' | 'critical';
}) {
  const toneClass = tone === 'good' ? 'text-good'
    : tone === 'warning' ? 'text-warning'
    : tone === 'critical' ? 'text-critical' : 'text-ink';
  return (
    <div className="px-3.5 py-3">
      <p className="text-[11px] uppercase tracking-wide text-muted">{label}</p>
      <p className={`num mt-1 font-mono text-[22px] leading-tight ${toneClass}`}>
        {value}
        {unit && <span className="ml-1 text-[12px] font-normal text-muted">{unit}</span>}
      </p>
      {hint && <p className="mt-0.5 text-[11px] leading-4 text-muted">{hint}</p>}
    </div>
  );
}

const STATUS = {
  good:     { Icon: CheckCircle,    cls: 'text-good',     ring: 'border-good/30 bg-good/10' },
  warning:  { Icon: Warning,        cls: 'text-warning',  ring: 'border-warning/40 bg-warning/10' },
  serious:  { Icon: Warning,        cls: 'text-serious',  ring: 'border-serious/40 bg-serious/10' },
  critical: { Icon: WarningOctagon, cls: 'text-critical', ring: 'border-critical/40 bg-critical/10' },
  info:     { Icon: Info,           cls: 'text-muted',    ring: 'border-line bg-raised' },
} as const;

/** Status never travels as colour alone: icon plus label, every time. */
export function StatusPill({ kind, children }: {
  kind: keyof typeof STATUS; children: ReactNode;
}) {
  const { Icon, cls, ring } = STATUS[kind];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-pill border px-2 py-0.5 text-[11px] font-medium ${ring} ${cls}`}>
      <Icon size={12} weight="fill" aria-hidden />
      {children}
    </span>
  );
}

export function Empty({ icon, title, body }: { icon: ReactNode; title: string; body: string }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <span className="text-muted">{icon}</span>
      <p className="text-[13px] font-medium">{title}</p>
      <p className="max-w-[46ch] text-[12px] leading-5 text-muted">{body}</p>
    </div>
  );
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}
