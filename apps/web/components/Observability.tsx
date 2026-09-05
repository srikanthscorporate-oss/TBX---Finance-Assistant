'use client';

import { useCallback, useEffect, useState } from 'react';
import { ArrowsClockwise, ChartBar, CheckCircle, ShieldCheck, Warning } from '@phosphor-icons/react';
import { getEvaluations, getJudge, getUsage, HISTORY_CLEARED_EVENT } from '@/lib/api';
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

  useEffect(() => {
    load();
    const t = setInterval(load, 10_000);
    window.addEventListener(HISTORY_CLEARED_EVENT, load);
    return () => { clearInterval(t); window.removeEventListener(HISTORY_CLEARED_EVENT, load); };
  }, [load]);

  if (loading) return <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div>;
  if (error) return <Panel><Empty icon={<Warning size={24} weight="fill" />} title="Cannot reach the metrics API" body={error} /></Panel>;

  const noRuns = !usage || usage.runs === 0;
  const recent = usage?.recent ?? [];
  const split = usage?.time_split_ms;

  return (
    <div className="space-y-4">
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

      {evals?.available ? (() => {
        // A throttled attempt is not a measurement; report the last clean run.
        const clean = evals.last_clean && !evals.last_clean.throttled ? evals.last_clean : (evals.throttled ? null : evals);
        const eff = clean?.efficiency;
        return (
          <>
            {evals.throttled && (
              <div className="flex items-start gap-2.5 rounded border border-warning/40 bg-warning/[.07] px-3.5 py-3">
                <Warning size={15} weight="fill" aria-hidden className="mt-[2px] shrink-0 text-warning" />
                <div className="text-[12px] leading-5 text-ink-2">
                  <p className="font-medium text-ink">Latest attempt ({evals.generated_at?.replace('T', ' ').slice(0, 16)}) was throttled and is not a measurement.</p>
                  <p>{evals.rate_limited_calls} of {evals.turns} turns were refused before any model call because every
                    provider was rate limited. Nothing was guessed. {clean ? 'The measurement below is the last clean run.' : 'No clean run is on disk yet; the evaluation re-runs automatically when quota recovers.'}</p>
                </div>
              </div>
            )}
            {clean?.planner === 'stub' && (
              <div className="flex items-start gap-2.5 rounded border border-warning/40 bg-warning/[.07] px-3.5 py-3">
                <Warning size={15} weight="fill" aria-hidden className="mt-[2px] shrink-0 text-warning" />
                <p className="text-[12px] leading-5 text-ink-2">These scores came from the offline stub planner: they measure the deterministic pipeline, not natural-language accuracy.</p>
              </div>
            )}
            <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
              <Panel>
                <PanelHead title="Golden set"
                  meta={clean ? `${clean.questions} questions, ${clean.turns} turns, measured ${clean.generated_at?.slice(0, 10)}` : `${evals.questions} questions, ${evals.turns} turns`}
                  actions={clean
                    ? <StatusPill kind={(clean.grounding_rate ?? 0) >= 1 ? 'good' : 'warning'}>Grounding {pct(clean.grounding_rate ?? 0, 0)}</StatusPill>
                    : <StatusPill kind="info">Not measured yet</StatusPill>} />
                {clean ? (
                  <div className="grid grid-cols-1 gap-2 p-2 sm:grid-cols-3">
                    <RadialGauge value={clean.overall_accuracy ?? 0} label="overall" tone="status" size={150} />
                    <RadialGauge value={clean.numeric_accuracy ?? 0} label="numeric" size={150} />
                    <RadialGauge value={clean.hallucination_free_rate ?? 0} label="hallucination free" tone="status" size={150} />
                  </div>
                ) : (
                  <Empty icon={<ShieldCheck size={24} />} title="No clean measurement on disk"
                         body="The only evaluation so far ran while every model was rate limited. It re-runs automatically when quota recovers; nothing here is a score." />
                )}
                <ul className="divide-y divide-line-soft border-t border-line">
                  {[['Verification pass rate', 'verification_pass_rate', 'blocking checks veto an answer'],
                    ['Hallucination free', 'hallucination_free_rate', 'no unverified figures'],
                    ['Numeric accuracy', 'numeric_accuracy', 'against independent computation'],
                    ['Counterparty resolution', 'counterparty_resolution_accuracy', 'correct counterparty chosen']].map(([label, key, hint]) => {
                    const v = clean ? ((clean as unknown) as Record<string, number>)[key as string] : null;
                    return (
                      <li key={label as string} className="flex items-center gap-3 px-3.5 py-2.5">
                        {v == null ? <span aria-hidden className="h-[15px] w-[15px] shrink-0 rounded-pill border border-line" />
                          : v >= 1 ? <CheckCircle size={15} weight="fill" aria-hidden className="shrink-0 text-good" />
                          : <Warning size={15} weight="fill" aria-hidden className="shrink-0 text-warning" />}
                        <div className="min-w-0"><p className="text-[12.5px]">{label as string}</p><p className="text-[11px] text-muted">{hint as string}</p></div>
                        <p className="num ml-auto font-mono text-[13px]">{v == null ? 'not measured' : pct(v, 0)}</p>
                      </li>);
                  })}
                </ul>
              </Panel>
              <ChartFrame title="Accuracy by question category"
                hint={clean ? 'One measure across categories: colour carries magnitude only.' : 'Appears after the first clean run.'}>
                {clean ? (
                  <>
                    <BarSeries horizontal height={330} format={(n: number) => `${Math.round(n * 100)}%`}
                      data={Object.entries(clean.by_category ?? {}).sort((a, b) => b[1].accuracy - a[1].accuracy)
                        .map(([k, v]) => ({ label: k.replace(/_/g, ' '), value: v.accuracy }))} />
                    {eff && (
                      <div className="mt-2 grid grid-cols-3 gap-2 border-t border-line-soft px-2 pt-3 text-center">
                        {[['Tokens per turn', compactNumber(eff.avg_tokens_per_turn)], ['Switch rate', pct(eff.escalation_rate, 1)],
                          ['p95 latency', ms(eff.latency_p95_ms)]].map(([k, v]) => (
                          <div key={k}><p className="num font-mono text-[15px]">{v}</p><p className="text-[10.5px] text-muted">{k}</p></div>))}
                      </div>
                    )}
                  </>
                ) : (
                  <Empty icon={<ChartBar size={24} />} title="Not measured yet" body="Category accuracy is drawn from the last clean evaluation run." />
                )}
              </ChartFrame>
            </div>
          </>
        );
      })() : (
        <Panel><PanelHead title="Golden set" />
          <Empty icon={<ShieldCheck size={24} />} title="No evaluation report yet"
                 body={evals?.hint ?? 'Run scripts/run_evaluation.py to measure accuracy and efficiency.'} /></Panel>
      )}

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
                  {h.available === false
                    ? <StatusPill kind="info">no key</StatusPill>
                    : h.breaker_open_s > 0
                    ? <StatusPill kind="warning">rate limited, {h.breaker_open_s}s</StatusPill>
                    : h.quality_open
                    ? <StatusPill kind="critical">paused: low validity</StatusPill>
                    : <StatusPill kind="good">live</StatusPill>}
                </li>
              ))}
            </ul>
            {judge.recent.length > 0 && (() => {
              const counts = judge.recent.reduce<Record<string, number>>((a, r) => { a[r.state] = (a[r.state] ?? 0) + 1; return a; }, {});
              const tone = (sc: number) => sc >= 0.85 ? 'var(--good)' : sc >= 0.6 ? 'var(--warning)' : 'var(--critical)';
              return (
                <div className="mt-2 border-t border-line-soft px-2 pt-3">
                  <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1">
                    <p className="text-[11px] uppercase tracking-wide text-muted">Recent verdicts</p>
                    {Object.entries(counts).map(([k, n]) => (
                      <span key={k} className="text-[11.5px] text-ink-2">{n} {STATE_LABEL[k]?.toLowerCase() ?? k}</span>))}
                    <span className="ml-auto flex items-center gap-3 text-[10.5px] text-muted">
                      <span className="flex items-center gap-1"><span aria-hidden className="h-2 w-2 rounded-[2px]" style={{ background: 'var(--good)' }} />verified answer</span>
                      <span className="flex items-center gap-1"><span aria-hidden className="h-2 w-2 rounded-[2px]" style={{ background: 'var(--warning)' }} />correct refusal</span>
                      <span className="flex items-center gap-1"><span aria-hidden className="h-2 w-2 rounded-[2px]" style={{ background: 'var(--critical)' }} />error</span>
                    </span>
                  </div>
                  <ul className="divide-y divide-line-soft">
                    {judge.recent.slice(0, 8).map(r => (
                      <li key={r.run_id} className="flex items-center gap-3 py-1.5 text-[12px]">
                        <span aria-hidden className="h-3 w-1.5 shrink-0 rounded-[2px]" style={{ background: tone(r.score) }} />
                        <span className="w-[118px] shrink-0 text-ink">{STATE_LABEL[r.state] ?? r.state}</span>
                        <span className="min-w-0 flex-1 truncate text-ink-2" title={r.notes.join('; ')}>{r.notes[0] ?? ''}{r.cache_hit ? ` (${r.cache_hit} from cache)` : ''}</span>
                        <span className="num hidden w-24 shrink-0 font-mono text-[11px] text-muted sm:block">{r.model ?? 'no model'}</span>
                        <span className="num w-16 shrink-0 text-right font-mono text-[11px] text-muted">{r.tokens ? `${r.tokens.toLocaleString()} tok` : '0 tok'}</span>
                        <span className="num w-14 shrink-0 text-right font-mono text-[11px] text-muted">{ms(r.duration_ms)}</span>
                      </li>))}
                  </ul>
                </div>
              );
            })()}
          </ChartFrame>
        </div>
      )}

      {!noRuns && (
        <Panel>
          <PanelHead title="Recent runs" meta="newest first; operational fields only, never financial data" />
          <RecentRuns runs={recent} />
        </Panel>
      )}
    </div>
  );
}
