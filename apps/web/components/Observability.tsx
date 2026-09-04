'use client';

import { useCallback, useEffect, useState } from 'react';
import { ArrowsClockwise, ChartBar, CheckCircle, ShieldCheck, Warning } from '@phosphor-icons/react';
import { getEvaluations, getJudge, getUsage } from '@/lib/api';
import type { EvalReport, JudgeSummary, RecentRun, Usage } from '@/lib/types';
import { compactNumber, ms, pct } from '@/lib/format';
import { BarSeries, ChartFrame, CompositionBar, RadialGauge, RingChart, Sparkline, TimingBar } from './charts';
import { Empty, Panel, PanelHead, Skeleton, StatusPill } from './ui';

const TIER_LABEL: Record<string, string> = {
  primary: 'Primary', alternate: 'Alternate', fallback: 'Fallback', regional: 'Regional', pinned: 'Pinned by user',
};
const STATE_LABEL: Record<string, string> = {
  answer: 'Answered', clarification_required: 'Asked for detail',
  data_unavailable: 'Data absent', out_of_scope: 'Out of scope', error: 'Error',
};

/** A stat with its recent trend beside it. The number is the point; the line is context. */
function Tile({ label, value, unit, hint, series, tone }: {
  label: string; value: string; unit?: string; hint?: string; series?: number[];
  tone?: 'good' | 'warning' | 'critical';
}) {
  const cls = tone === 'good' ? 'text-good' : tone === 'warning' ? 'text-warning' : tone === 'critical' ? 'text-critical' : 'text-ink';
  return (
    <div className="flex items-end justify-between gap-3 px-3.5 py-3">
      <div className="min-w-0">
        <p className="text-[11px] uppercase tracking-wide text-muted">{label}</p>
        <p className={`num mt-1 font-mono text-[22px] leading-tight ${cls}`}>
          {value}{unit && <span className="ml-1 text-[12px] font-normal text-muted">{unit}</span>}
        </p>
        {hint && <p className="mt-0.5 text-[11px] leading-4 text-muted">{hint}</p>}
      </div>
      {series && series.length > 1 && <Sparkline values={series} />}
    </div>
  );
}

function RecentRuns({ runs }: { runs: RecentRun[] }) {
  const rows = [...runs].reverse().slice(0, 12);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12px]">
        <caption className="sr-only">Recent runs, newest first</caption>
        <thead>
          <tr className="border-b border-line text-muted">
            <th scope="col" className="px-3.5 py-2 text-left font-medium">When</th>
            <th scope="col" className="px-3.5 py-2 text-left font-medium">Outcome</th>
            <th scope="col" className="px-3.5 py-2 text-left font-medium">Model</th>
            <th scope="col" className="px-3.5 py-2 text-right font-medium">Time</th>
            <th scope="col" className="px-3.5 py-2 text-right font-medium">Tokens</th>
            <th scope="col" className="px-3.5 py-2 text-left font-medium">Split</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => {
            const total = r.duration_ms || 1;
            return (
              <tr key={r.run_id} className="border-b border-line-soft last:border-0">
                <td className="num px-3.5 py-2 font-mono text-[11px] text-muted">{r.at.slice(11, 19)}</td>
                <td className="px-3.5 py-2">
                  <span className={r.state === 'answer' ? 'text-good' : r.state === 'error' ? 'text-critical' : 'text-ink-2'}>
                    {STATE_LABEL[r.state] ?? r.state}
                  </span>
                  {r.switched && <span className="ml-1.5 text-[10.5px] text-warning">switched</span>}
                </td>
                <td className="px-3.5 py-2 font-mono text-[11px] text-ink-2">{r.model ?? '-'}</td>
                <td className="num px-3.5 py-2 text-right font-mono">{r.duration_ms ? ms(r.duration_ms) : '-'}</td>
                <td className="num px-3.5 py-2 text-right font-mono text-muted">{r.tokens.toLocaleString()}</td>
                <td className="px-3.5 py-2">
                  <div className="flex h-1.5 w-24 gap-[2px] overflow-hidden rounded-pill" aria-hidden>
                    <span style={{ width: `${(r.llm_ms / total) * 100}%`, background: 'var(--cat-1)' }} />
                    <span style={{ width: `${(r.query_ms / total) * 100}%`, background: 'var(--cat-2)' }} />
                    <span style={{ flex: 1, background: 'var(--cat-3)' }} />
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function Observability({ initialUsage, initialEvals, initialJudge }: {
  initialUsage: Usage | null; initialEvals: EvalReport | null; initialJudge?: JudgeSummary | null;
}) {
  const [usage, setUsage] = useState<Usage | null>(initialUsage);
  const [evals, setEvals] = useState<EvalReport | null>(initialEvals);
  const [judge, setJudge] = useState<JudgeSummary | null>(initialJudge ?? null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(initialUsage === null);

  const load = useCallback(async () => {
    try {
      const [u, e, j] = await Promise.all([getUsage(), getEvaluations(), getJudge().catch(() => null)]);
      setUsage(u); setEvals(e); setJudge(j); setError(null);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); const t = setInterval(load, 10_000); return () => clearInterval(t); }, [load]);

  if (loading) return <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div>;
  if (error) return <Panel><Empty icon={<Warning size={24} weight="fill" />} title="Cannot reach the metrics API" body={error} /></Panel>;

  const noRuns = !usage || usage.runs === 0;
  const recent = usage?.recent ?? [];
  const eff = evals?.efficiency;
  const split = usage?.time_split_ms;

  return (
    <div className="space-y-4">
      {/* 1. The numbers that matter, each with its trend ------------------ */}
      <Panel>
        <PanelHead title="This session" meta={noRuns ? undefined : `${usage!.runs} runs`}
          actions={<button onClick={load} aria-label="Refresh metrics"
            className="flex items-center gap-1.5 rounded-sm border border-line px-2 py-1 text-[11.5px] text-muted hover:text-ink">
            <ArrowsClockwise size={12} weight="bold" aria-hidden /> Refresh</button>} />
        {noRuns ? (
          <Empty icon={<ChartBar size={24} />} title="No runs recorded yet"
                 body="Ask a question and its cost, latency and model mix will appear here." />
        ) : (
          <div className="grid divide-y divide-line sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4 [&>*]:border-line sm:[&>*:not(:first-child)]:border-l">
            <Tile label="Tokens per run" value={compactNumber(usage!.avg_tokens_per_run)}
                  hint={`${compactNumber(usage!.total_tokens)} total`} series={recent.map(r => r.tokens)} />
            <Tile label="Latency" value={ms(usage!.latency_p50_ms)} unit="p50"
                  hint={`p95 ${ms(usage!.latency_p95_ms)}`} series={recent.map(r => r.duration_ms ?? 0)}
                  tone={usage!.latency_p95_ms > 4000 ? 'warning' : 'good'} />
            <Tile label="Cost per run" value={`$${usage!.avg_cost_per_run_usd.toFixed(5)}`}
                  hint={`$${usage!.total_cost_usd.toFixed(4)} total`} />
            <Tile label="Model switches" value={pct(usage!.escalation_rate, 0)}
                  hint="runs that needed a second model" tone={usage!.escalation_rate > 0.3 ? 'warning' : 'good'} />
          </div>
        )}
      </Panel>

      {/* 2. Time and models --------------------------------------------- */}
      {!noRuns && (
        <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <ChartFrame title="Where the time goes" hint="Model calls against database work against everything else, summed across the session.">
            <div className="px-2 pb-1 pt-2">
              {split && <TimingBar llm={split.llm} query={split.query} other={split.other} height={14} />}
            </div>
          </ChartFrame>
          <ChartFrame title="Model mix" hint="Every model here is under the 20B ceiling. There is no larger tier.">
            <div className="px-2 pb-1 pt-2 space-y-4">
              <CompositionBar parts={Object.entries(usage!.tier_calls).sort((a, b) => b[1] - a[1])
                .map(([k, v]) => ({ label: TIER_LABEL[k] ?? k, value: v }))} />
              <div className="border-t border-line-soft pt-3">
                <p className="mb-2 text-[11.5px] text-muted">Outcomes</p>
                <CompositionBar parts={Object.entries(usage!.states).sort((a, b) => b[1] - a[1])
                  .map(([k, v]) => ({ label: STATE_LABEL[k] ?? k, value: v }))} />
              </div>
            </div>
          </ChartFrame>
        </div>
      )}

      {/* 3. Evaluation --------------------------------------------------- */}
      {evals?.available ? (
        <>
          {evals.throttled && (
            <div className="flex items-start gap-2.5 rounded border border-critical/40 bg-critical/[.06] px-3.5 py-3">
              <Warning size={15} weight="fill" aria-hidden className="mt-[2px] shrink-0 text-critical" />
              <p className="text-[12px] leading-5 text-ink-2">
                This run was throttled: {evals.rate_limited_calls} model calls hit a provider rate
                limit, so the scores below understate the pipeline. Re-run when quota has recovered.
              </p>
            </div>
          )}
          {evals.planner === 'stub' && (
            <div className="flex items-start gap-2.5 rounded border border-warning/40 bg-warning/[.07] px-3.5 py-3">
              <Warning size={15} weight="fill" aria-hidden className="mt-[2px] shrink-0 text-warning" />
              <p className="text-[12px] leading-5 text-ink-2">
                These scores came from the offline stub planner. They measure the deterministic
                pipeline, not natural-language accuracy.
              </p>
            </div>
          )}
          <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
            <Panel>
              <PanelHead title="Golden set" meta={`${evals.questions} questions, ${evals.turns} turns`}
                actions={<StatusPill kind={(evals.grounding_rate ?? 0) >= 1 ? 'good' : 'warning'}>Grounding {pct(evals.grounding_rate ?? 0, 0)}</StatusPill>} />
              <div className="grid grid-cols-1 gap-2 p-2 sm:grid-cols-3">
                <RadialGauge value={evals.overall_accuracy ?? 0} label="overall" tone="status" size={150} />
                <RadialGauge value={evals.numeric_accuracy ?? 0} label="numeric" size={150} />
                <RadialGauge value={evals.hallucination_free_rate ?? 0} label="hallucination free" tone="status" size={150} />
              </div>
              <ul className="divide-y divide-line-soft border-t border-line">
                {[['Verification pass rate', evals.verification_pass_rate ?? 0, 'blocking checks veto an answer'],
                  ['Hallucination free', evals.hallucination_free_rate ?? 0, 'no unverified figures'],
                  ['Numeric accuracy', evals.numeric_accuracy ?? 0, 'against independent computation'],
                  ['Vendor resolution', evals.vendor_resolution_accuracy ?? 0, 'correct entity chosen']].map(([label, v, hint]) => (
                  <li key={String(label)} className="flex items-center gap-3 px-3.5 py-2.5">
                    {(v as number) >= 1 ? <CheckCircle size={15} weight="fill" aria-hidden className="shrink-0 text-good" />
                                        : <Warning size={15} weight="fill" aria-hidden className="shrink-0 text-warning" />}
                    <div className="min-w-0"><p className="text-[12.5px]">{label as string}</p><p className="text-[11px] text-muted">{hint as string}</p></div>
                    <p className="num ml-auto font-mono text-[13px]">{pct(v as number, 0)}</p>
                  </li>))}
              </ul>
            </Panel>
            <ChartFrame title="Accuracy by question category" hint="One measure across categories: colour carries magnitude only.">
              <BarSeries horizontal height={330} format={(n: number) => `${Math.round(n * 100)}%`}
                data={Object.entries(evals.by_category ?? {}).sort((a, b) => b[1].accuracy - a[1].accuracy)
                  .map(([k, v]) => ({ label: k.replace(/_/g, ' '), value: v.accuracy }))} />
              {eff && (
                <div className="mt-2 grid grid-cols-3 gap-2 border-t border-line-soft px-2 pt-3 text-center">
                  {[['Tokens per turn', compactNumber(eff.avg_tokens_per_turn)], ['Switch rate', pct(eff.escalation_rate, 1)],
                    ['p95 latency', ms(eff.latency_p95_ms)]].map(([k, v]) => (
                    <div key={k}><p className="num font-mono text-[15px]">{v}</p><p className="text-[10.5px] text-muted">{k}</p></div>))}
                </div>
              )}
            </ChartFrame>
          </div>
        </>
      ) : (
        <Panel><PanelHead title="Golden set" />
          <Empty icon={<ShieldCheck size={24} />} title="No evaluation report yet"
                 body={evals?.hint ?? 'Run scripts/run_evaluation.py to measure accuracy and efficiency.'} /></Panel>
      )}

      {/* 4. The judge ----------------------------------------------------- */}
      {judge?.enabled && (
        <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
          <ChartFrame title="Judge" hint="Scores every run, caches plans and answers, breaks circuits on rate limits, and steers Auto toward the model producing valid plans.">
            <div className="px-2 pb-1 pt-2 space-y-4">
              <RingChart centre={`${Math.round((judge.cache.hit_rate ?? 0) * 100)}%`} sub="cache hits" size={124}
                parts={[{ label: 'Plan reused', value: judge.cache.plan }, { label: 'Answer reused', value: judge.cache.answer },
                        { label: 'Computed fresh', value: judge.cache.miss }]} />
              <div className="grid grid-cols-2 gap-2 border-t border-line-soft pt-3 text-center">
                <div><p className="num font-mono text-[18px]">{judge.avg_score == null ? '-' : judge.avg_score.toFixed(2)}</p><p className="text-[10.5px] text-muted">average verdict</p></div>
                <div><p className="num font-mono text-[18px]">{judge.runs_scored}</p><p className="text-[10.5px] text-muted">runs scored</p></div>
              </div>
            </div>
          </ChartFrame>
          <ChartFrame title="Model health" hint="Plan validity over the last hour, and which circuits are open.">
            <ul className="divide-y divide-line-soft px-2">
              {Object.entries(judge.models).map(([m, h]) => (
                <li key={m} className="flex items-center gap-3 py-2.5">
                  <span className="w-28 shrink-0 font-mono text-[12px]">{m}</span>
                  <div className="flex h-2 flex-1 overflow-hidden rounded-pill bg-line-soft" aria-hidden>
                    <span style={{ width: `${Math.round((h.plan_validity ?? 0) * 100)}%`, background: 'var(--seq-5)' }} />
                  </div>
                  <span className="num w-14 text-right font-mono text-[12px]">{h.plan_validity == null ? 'n/a' : pct(h.plan_validity, 0)}</span>
                  <span className="w-16 text-[10.5px] text-muted">{h.samples} plans</span>
                  {h.breaker_open_s > 0
                    ? <StatusPill kind="warning">paused {h.breaker_open_s}s</StatusPill>
                    : <StatusPill kind="good">live</StatusPill>}
                </li>
              ))}
            </ul>
            {judge.recent.length > 0 && (
              <div className="mt-2 border-t border-line-soft px-2 pt-2">
                <p className="mb-1 text-[11px] text-muted">Recent verdicts</p>
                <div className="flex flex-wrap gap-1" aria-label="recent verdict scores">
                  {judge.recent.slice(0, 40).map(r => (
                    <span key={r.run_id} title={`${r.state}${r.cache_hit ? `, ${r.cache_hit} cached` : ''}${r.notes.length ? `: ${r.notes.join('; ')}` : ''}`}
                      className="h-5 w-3 rounded-[2px]"
                      style={{ background: r.score >= 0.85 ? 'var(--good)' : r.score >= 0.6 ? 'var(--warning)' : 'var(--critical)',
                               opacity: r.cache_hit ? 0.55 : 1 }} />
                  ))}
                </div>
              </div>
            )}
          </ChartFrame>
        </div>
      )}

      {/* 5. Recent runs -------------------------------------------------- */}
      {!noRuns && (
        <Panel>
          <PanelHead title="Recent runs" meta="newest first; operational fields only, never financial data" />
          <RecentRuns runs={recent} />
        </Panel>
      )}
    </div>
  );
}
