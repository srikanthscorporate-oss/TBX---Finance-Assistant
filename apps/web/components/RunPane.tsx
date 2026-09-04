'use client';

import {
  Broadcast, Database, Info, PulseIcon, Question, WarningOctagon,
} from '@phosphor-icons/react';
import type { DatasetInfo, Turn } from '@/lib/types';
import { buildStages } from '@/lib/stages';
import { exportUrl } from '@/lib/api';
import { fullMoney, ms } from '@/lib/format';
import Breakdown from './Breakdown';
import EvidencePanel from './EvidencePanel';
import StageRail from './StageRail';
import { StatusPill } from './ui';

const NON_ANSWER = {
  clarification_required: { Icon: Question,       label: 'Needs one detail', cls: 'text-warning' },
  data_unavailable:       { Icon: Database,       label: 'Not in this data', cls: 'text-muted' },
  out_of_scope:           { Icon: Info,           label: 'Outside my scope', cls: 'text-muted' },
  error:                  { Icon: WarningOctagon, label: 'Could not answer', cls: 'text-critical' },
} as const;

function Idle({ dataset }: { dataset: DatasetInfo | null }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-8 text-center">
      <PulseIcon size={26} className="text-muted" aria-hidden />
      <p className="text-[13px] font-medium">Nothing running</p>
      <p className="max-w-[42ch] text-[12px] leading-5 text-muted">
        Ask a question and every step the assistant takes will appear here as it
        happens: what it resolved, what it queried, and what it verified before
        answering.
      </p>
      {dataset && (
        <dl className="mt-2 grid w-full max-w-[300px] grid-cols-2 gap-x-4 gap-y-1.5 border-t border-line pt-3 text-left">
          {[
            ['Dataset', dataset.dataset_version],
            ['Coverage', `${dataset.min_date} to ${dataset.max_date}`],
            ['Vendors', String(dataset.vendor_count)],
            ['Currency', dataset.currency],
          ].map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-[11px] text-muted">{k}</dt>
              <dd className="num truncate font-mono text-[11px] text-ink-2" title={v}>{v}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

export default function RunPane({ turn, dataset }: {
  turn: Turn | null;
  dataset: DatasetInfo | null;
}) {
  if (!turn) return <Idle dataset={dataset} />;

  const res = turn.response;
  const stages = buildStages(turn.events, turn.running);
  const ev = res?.evidence;
  const headline = ev?.facts.find(f => ['total', 'shown_total', 'count', 'rate'].includes(f.key));
  const meta = res && res.state !== 'answer' ? NON_ANSWER[res.state] : null;
  const tokens = (res?.model_usage ?? []).reduce((a, u) => a + u.prompt_tokens + u.completion_tokens, 0);
  const escalated = (res?.model_usage ?? []).some(u => u.tier === 'escalation');
  const models = [...new Set((res?.model_usage ?? []).map(u => u.model.split('/').pop()!))];

  return (
    <div className="flex h-full flex-col">
      {/* Live status strip ------------------------------------------------ */}
      <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        {turn.running ? (
          <span className="flex items-center gap-1.5 text-[11.5px] text-accent">
            <Broadcast size={13} weight="fill" aria-hidden className="spin" />
            Working
          </span>
        ) : res?.state === 'answer' ? (
          <StatusPill kind="good">Answered</StatusPill>
        ) : meta ? (
          <span className={`flex items-center gap-1.5 text-[11.5px] ${meta.cls}`}>
            <meta.Icon size={13} weight="fill" aria-hidden />
            {meta.label}
          </span>
        ) : null}

        {escalated && (
          <StatusPill kind="warning">Escalated to a larger model</StatusPill>
        )}

        <p className="num ml-auto font-mono text-[11px] text-muted">
          {[
            res?.duration_ms ? ms(res.duration_ms) : null,
            tokens ? `${tokens.toLocaleString()} tok` : null,
            res?.model_usage?.length ? `${res.model_usage.length} calls` : null,
            models.length ? models.join(', ') : null,
          ].filter(Boolean).join('  ')}
        </p>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {/* Headline figure. A number this important is not a chart. */}
        {headline && (
          <div>
            <p className="text-[11px] uppercase tracking-wide text-muted">
              {ev?.entities_resolved?.vendor_name
                ? `${ev.entities_resolved.vendor_name}, ${ev?.resolved_period ?? 'all time'}`
                : (ev?.resolved_period ?? 'All time')}
            </p>
            <p className="num mt-1 font-mono text-[30px] leading-none tracking-tight">
              {headline.formatted}
            </p>
            <p className="mt-1.5 text-[11.5px] text-muted">
              {headline.key === 'shown_total'
                ? 'Combined value of the groups shown below, limited by the row cap.'
                : `Computed across ${ev?.total_record_count.toLocaleString()} records.`}
            </p>
          </div>
        )}

        {/* The alive part: stage-by-stage progress. */}
        <section>
          <h3 className="mb-2.5 text-[11px] uppercase tracking-wide text-muted">Pipeline</h3>
          <StageRail stages={stages} />
        </section>

        {ev && ev.breakdown.length > 0 && (
          <Breakdown
            rows={ev.breakdown}
            chartHint={res?.chart_hint}
            currency={ev.currency}
            exportHref={exportUrl({
              intent: String(res?.plan?.intent ?? 'total_spend'),
              group_by: String(res?.plan?.group_by ?? 'vendor'),
              metric: String(res?.plan?.metric ?? 'sum'),
              relative: (res?.plan?.date_range as { relative?: string })?.relative,
              vendor_id: res?.plan?.vendor_id as string | undefined,
              category: res?.plan?.category as string | undefined,
            })}
          />
        )}

        {ev && <EvidencePanel evidence={ev} />}

        {turn.error && (
          <p className="rounded border border-critical/40 bg-critical/[.07] px-3 py-2.5
                        text-[12.5px] text-critical">{turn.error}</p>
        )}
      </div>
    </div>
  );
}
