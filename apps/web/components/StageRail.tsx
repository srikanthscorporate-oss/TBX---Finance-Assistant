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

/**
 * One line per stage: name, a single-phrase summary of what it did, and how
 * long it took. The full detail lives in the evidence panel; this rail is for
 * following progress, not auditing it.
 */
function summary(s: StageState): string {
  const d = stageDetail(s);
  const get = (k: string) => d.find(([key]) => key === k)?.[1];
  switch (s.key) {
    case 'understand': return get('judge') ?? (get('intent') ? `${get('intent')}${get('metric') ? `, ${get('metric')}` : ''}` : (get('reason') ? `not relevant: ${get('reason')}` : ''));
    case 'resolve': {
      const v = get('vendor'), from = get('from'), to = get('to');
      return [v && v.split(' to ')[0], from && to ? `${from} to ${to}` : null].filter(Boolean).join('; ');
    }
    case 'plan': return get('judge') ?? (d.length ? 'validated' : '');
    case 'query': return get('rows read') ? `${get('rows read')} rows read` : (get('query time') ?? '');
    case 'verify': return [get('checks passed'), get('confidence') && `confidence ${get('confidence')}`].filter(Boolean).join(', ');
    case 'answer': return [get('judge'), get('anomaly') && `anomaly ${get('anomaly')}`, get('verdict') && `score ${get('verdict')}`, get('escalated') && 'second model']
      .filter(Boolean).join('; ') || (s.status === 'done' ? 'composed' : '');
  }
}

export default function StageRail({ stages }: { stages: StageState[] }) {
  const doneCount = stages.filter(s => s.status === 'done').length;
  return (
    <div>
      {/* Progress as a segmented track: one cell per stage, filled as it completes. */}
      <div className="mb-3 flex gap-[3px]" role="progressbar" aria-valuemin={0} aria-valuemax={6}
           aria-valuenow={doneCount} aria-label="pipeline progress">
        {stages.map(s => (
          <span key={s.key} className={`h-1.5 flex-1 rounded-pill transition-colors ${
            s.status === 'done' ? 'bg-accent' : s.status === 'active' ? 'bg-accent/40'
            : s.status === 'failed' ? 'bg-critical' : 'bg-line'}`} />
        ))}
      </div>
      <ol className="space-y-2">
        {stages.map(s => {
          const { Icon, cls, spin } = MARK[s.status];
          const text = summary(s);
          return (
            <li key={s.key} className="rise flex items-start gap-2.5">
              <Icon size={14} weight={s.status === 'pending' ? 'regular' : 'fill'} aria-hidden
                    className={`shrink-0 ${cls} ${spin ? 'spin' : ''}`} />
              <span className={`w-[84px] shrink-0 text-[12.5px] font-medium ${
                s.status === 'pending' ? 'text-muted' : 'text-ink'}`}>{s.label}</span>
              <span className="min-w-0 flex-1 break-words text-[11.5px] leading-4 text-muted">{text}</span>
              {s.durationMs !== null && s.status === 'done' && (
                <span className="num shrink-0 font-mono text-[10.5px] text-muted">{s.durationMs}ms</span>
              )}
              {s.status === 'active' && (
                <span className="shrink-0 text-[10.5px] uppercase tracking-wide text-accent">running</span>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
