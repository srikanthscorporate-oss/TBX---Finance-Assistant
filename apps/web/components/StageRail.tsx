'use client';

import { CheckCircle, CircleDashed, CircleNotch, MinusCircle, WarningOctagon } from '@phosphor-icons/react';
import { stageDetail, type StageState } from '@/lib/stages';

const MARK = {
  done:    { Icon: CheckCircle,    cls: 'text-good',     spin: false },
  active:  { Icon: CircleNotch,    cls: 'text-accent',   spin: true  },
  failed:  { Icon: WarningOctagon, cls: 'text-critical', spin: false },
  skipped: { Icon: MinusCircle,    cls: 'text-muted',    spin: false },
  pending: { Icon: CircleDashed,   cls: 'text-muted',    spin: false },
} as const;

export default function StageRail({ stages }: { stages: StageState[] }) {
  return (
    <ol className="relative">
      {stages.map((s, i) => {
        const { Icon, cls, spin } = MARK[s.status];
        const detail = stageDetail(s);
        const last = i === stages.length - 1;
        const reached = s.status === 'done' || s.status === 'failed';

        return (
          <li key={s.key} className="relative flex gap-3 pb-3 last:pb-0">
            {/* Connector. Filled behind completed stages so progress reads vertically. */}
            {!last && (
              <span aria-hidden
                className={`absolute left-[7px] top-[18px] w-px ${reached ? 'bg-accent/40' : 'bg-line'}`}
                style={{ bottom: 0 }} />
            )}

            <Icon size={15} weight={s.status === 'pending' ? 'regular' : 'fill'} aria-hidden
              className={`relative z-10 mt-[2px] shrink-0 bg-surface ${cls} ${spin ? 'spin' : ''}`} />

            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2">
                <p className={`text-[12.5px] font-medium ${
                  s.status === 'pending' ? 'text-muted' : 'text-ink'}`}>
                  {s.label}
                </p>
                {s.durationMs !== null && s.status === 'done' && (
                  <span className="num font-mono text-[10.5px] text-muted">{s.durationMs}ms</span>
                )}
                {s.status === 'active' && (
                  <span className="text-[10.5px] uppercase tracking-wide text-accent">running</span>
                )}
              </div>

              {detail.length > 0 && (
                <dl className="mt-1 grid grid-cols-[minmax(0,auto)_1fr] gap-x-3 gap-y-0.5">
                  {detail.map(([k, v], j) => (
                    <div key={`${k}-${j}`} className="contents">
                      <dt className="text-[11px] text-muted">{k}</dt>
                      <dd className="num truncate font-mono text-[11px] text-ink-2" title={v}>{v}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
