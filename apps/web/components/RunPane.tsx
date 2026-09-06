'use client';

import { CaretRight, Database, Info, PulseIcon, Question, WarningOctagon } from '@phosphor-icons/react';
import { useState } from 'react';
import type { DatasetInfo, Evidence, Turn } from '@/lib/types';
import { buildStages } from '@/lib/stages';
import { exportUrl } from '@/lib/api';
import { compactMoney, fullMoney, ms } from '@/lib/format';
import { BarSeries, LineSeries, RingChart, SignalDots, TimingBar } from './charts';
import EvidencePanel from './EvidencePanel';
import StageRail from './StageRail';
import { StatusPill } from './ui';

const NON_ANSWER = {
  clarification_required: { Icon: Question,       label: 'Waiting for your answer', cls: 'text-warning' },
  data_unavailable:       { Icon: Database,       label: 'Not in this data',        cls: 'text-muted' },
  out_of_scope:           { Icon: Info,           label: 'Outside my scope',        cls: 'text-muted' },
  error:                  { Icon: WarningOctagon, label: 'Could not answer',        cls: 'text-critical' },
} as const;

function Idle({ dataset }: { dataset: DatasetInfo | null }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-8 text-center">
      <PulseIcon size={26} className="text-muted" aria-hidden />
      <p className="text-[13px] font-medium">Nothing running</p>
      <p className="max-w-[42ch] text-[12px] leading-5 text-muted">
        Ask a question on the left. Each stage appears here as it runs, then the
        figure, the charts, and the evidence behind them.
      </p>
      {dataset && (
        <dl className="mt-2 grid w-full max-w-[300px] grid-cols-2 gap-x-4 gap-y-1.5 border-t border-line pt-3 text-left">
          {[['Dataset', dataset.dataset_version], ['Coverage', `${dataset.min_date} to ${dataset.max_date}`],
            ['Accounts', String(dataset.account_count)], ['Counterparties', String(dataset.counterparty_count)],
            ['Banks', String(Object.keys(dataset.banks ?? {}).length)], ['Currency', dataset.currency]].map(([k, v]) => (
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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2.5 text-[11px] uppercase tracking-wide text-muted">{title}</h3>
      {children}
    </section>
  );
}

function Visuals({ ev, chartHint, exportHref }: { ev: Evidence; chartHint?: string | null; exportHref: string }) {
  const rows = ev.breakdown;
  const blocks: React.ReactNode[] = [];

  if (rows.length > 1) {
    const isTime = chartHint === 'line';
    const data = rows.map(r => ({ label: r.label, value: r.value }));
    blocks.push(
      <div key="series" className="rounded border border-line p-2 pt-3.5">
        <div className="mb-1 flex items-center px-1.5">
          <p className="text-[12px] text-ink-2">{isTime ? 'Over time' : 'By group'}</p>
          <a href={exportHref} download className="ml-auto text-[11px] text-muted hover:text-ink">CSV</a>
        </div>
        {isTime
          ? <LineSeries data={data} format={n => compactMoney(n, ev.currency)} height={190} />
          : <BarSeries data={data} horizontal format={n => compactMoney(n, ev.currency)}
                       height={Math.max(150, Math.min(rows.length * 24 + 36, 300))} />}
      </div>);

    if (!isTime && rows.length >= 3) {
      const top = rows.slice(0, 3).map(r => ({ label: r.label, value: r.value }));
      const rest = rows.slice(3).reduce((a, r) => a + r.value, 0);
      const total = rows.reduce((a, r) => a + r.value, 0) || 1;
      blocks.push(
        <div key="share" className="rounded border border-line p-3.5">
          <p className="mb-2 text-[12px] text-ink-2">Share of the total</p>
          <RingChart centre={`${Math.round((top[0].value / total) * 100)}%`} sub={top[0].label.split(' ')[0]}
            parts={rest > 0 ? [...top.slice(0, 2), { label: 'Everything else', value: rest + top[2].value }] : top} />
        </div>);
    }
  }
  if (!blocks.length) return null;
  return <div className="grid gap-3 sm:grid-cols-2">{blocks}</div>;
}

export default function RunPane({ turn, dataset }: { turn: Turn | null; dataset: DatasetInfo | null }) {
  const [showEvidence, setShowEvidence] = useState(false);
  if (!turn) return <Idle dataset={dataset} />;

  const res = turn.response;
  const ev = res?.evidence;
  const stages = buildStages(turn.events, turn.running);
  const headline = ev?.facts.find(f => ['total', 'balance_total', 'amount', 'shown_total', 'count'].includes(f.key));
  const meta = res && res.state !== 'answer' ? NON_ANSWER[res.state] : null;

  const calls = res?.model_usage ?? [];
  const llmMs = calls.reduce((a, u) => a + (u as { duration_ms?: number }).duration_ms!, 0) || 0;
  const queryMs = ev?.query_duration_ms ?? 0;
  const totalMs = res?.duration_ms ?? 0;
  const otherMs = Math.max(0, totalMs - llmMs - queryMs);
  const tokens = calls.reduce((a, u) => a + u.prompt_tokens + u.completion_tokens, 0);
  const switched = calls.some(u => ['alternate', 'fallback', 'regional'].includes(u.tier) && u.ok);

  const plan = res?.plan;
  const exportHref = exportUrl({
    intent: plan?.intent ?? 'spend_summary',
    group_by: plan?.group_by ?? 'counterparty',
    metric: plan?.metric ?? 'sum',
    relative: plan?.date_range?.relative ?? undefined,
    entity_id: plan?.entity_id ?? undefined,
    counterparty: plan?.counterparty ?? undefined,
    channel: plan?.channel ?? undefined,
    transaction_type: plan?.transaction_type ?? undefined,
  });
  const scope = ev ? (['counterparty', 'account', 'bank', 'channel'] as const)
    .filter(k => ev.entities_resolved[k])
    .map(k => k === 'account' ? `account ${ev.entities_resolved[k]}` : ev.entities_resolved[k]) : [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        {turn.running ? (
          <span className="flex items-center gap-1.5 text-[11.5px] text-accent">
            <PulseIcon size={13} weight="fill" aria-hidden className="spin" /> Working
          </span>
        ) : res?.state === 'answer' ? <StatusPill kind="good">Answered</StatusPill>
        : meta ? (
          <span className={`flex items-center gap-1.5 text-[11.5px] ${meta.cls}`}>
            <meta.Icon size={13} weight="fill" aria-hidden />{meta.label}
          </span>
        ) : null}
        {switched && <StatusPill kind="warning">Needed a second model</StatusPill>}
        <p className="num ml-auto font-mono text-[11px] text-muted">
          {[totalMs ? ms(totalMs) : null, tokens ? `${tokens.toLocaleString()} tok` : null]
            .filter(Boolean).join('   ')}
        </p>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto overflow-x-hidden p-4 [overflow-wrap:anywhere]">
        {headline && ev && (
          <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
            <div>
              <p className="text-[11px] uppercase tracking-wide text-muted">
                {scope.length
                  ? `${scope.join(', ')}, ${ev.resolved_period ?? (headline.key === 'balance_total' ? 'current' : 'all time')}`
                  : (ev.resolved_period ?? (headline.key === 'balance_total' ? 'Current balance' : 'All time'))}
              </p>
              <p className="num mt-1 font-mono text-[34px] leading-none tracking-tight">{headline.formatted}</p>
              <p className="mt-1.5 text-[11.5px] text-muted">
                {headline.key === 'shown_total'
                  ? 'Combined value of the rows shown, limited by the row cap.'
                  : headline.key === 'balance_total'
                    ? `Available balance across ${ev.total_record_count.toLocaleString()} account${ev.total_record_count === 1 ? '' : 's'}.`
                    : `Computed across ${ev.total_record_count.toLocaleString()} transactions.`}
              </p>
            </div>
            {ev.confidence && (
              <div className="rounded border border-line px-3 py-2">
                <p className="text-[10.5px] uppercase tracking-wide text-muted">Confidence</p>
                <p className={`num font-mono text-[18px] ${
                  ev.confidence.band === 'high' ? 'text-good' : ev.confidence.band === 'medium' ? 'text-warning' : 'text-critical'}`}>
                  {Math.round(ev.confidence.score * 100)}%
                </p>
              </div>
            )}
          </div>
        )}

        <Section title="Pipeline"><StageRail stages={stages} /></Section>

        {totalMs > 0 && (
          <Section title="Where the time went">
            <TimingBar llm={llmMs} query={queryMs} other={otherMs} />
          </Section>
        )}

        {ev && (
          <Section title="Visuals">
            <Visuals ev={ev} chartHint={res?.chart_hint} exportHref={exportHref} />
            {!ev.breakdown.length && (
              <p className="text-[11.5px] text-muted">
                {ev.records.length
                  ? 'Individual transactions are listed under Evidence. Ask for a breakdown by counterparty, channel or month to see a chart.'
                  : 'A single figure. Ask for a breakdown or a trend to see it charted.'}
              </p>
            )}
          </Section>
        )}

        {ev?.confidence && (
          <Section title="Confidence signals"><SignalDots signals={ev.confidence.signals} /></Section>
        )}

        {ev && (
          <section>
            <button onClick={() => setShowEvidence(v => !v)} aria-expanded={showEvidence}
              className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted hover:text-ink">
              <CaretRight size={11} weight="bold" aria-hidden className={`transition-transform ${showEvidence ? 'rotate-90' : ''}`} />
              Evidence
              <span className="normal-case tracking-normal">
                {ev.verification.checks.filter(c => c.passed).length} of {ev.verification.checks.length} checks, facts, SQL{ev.records.length ? `, ${ev.records.length} records` : ''}
              </span>
            </button>
            {showEvidence && <EvidencePanel evidence={ev} />}
          </section>
        )}

        {turn.error && (
          <p className="rounded border border-critical/40 bg-critical/[.07] px-3 py-2.5 text-[12.5px] text-critical">{turn.error}</p>
        )}
      </div>
    </div>
  );
}
