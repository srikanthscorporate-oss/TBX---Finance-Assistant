'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  ArrowsClockwise, ChartBar, CheckCircle, Cpu, Gauge, ShieldCheck, Warning,
} from '@phosphor-icons/react';
import { getEvaluations, getUsage } from '@/lib/api';
import type { EvalReport, Usage } from '@/lib/types';
import { compactNumber, ms, pct } from '@/lib/format';
import { BarSeries, ChartFrame, CompositionBar } from './charts';
import { Empty, Panel, PanelHead, Skeleton, Stat, StatusPill } from './ui';

const TIER_LABEL: Record<string, string> = {
  small: 'Small model', escalation: 'Escalated', fallback: 'Fallback', selfhosted: 'Self-hosted',
};

const STATE_LABEL: Record<string, string> = {
  answer: 'Answered', clarification_required: 'Asked for detail',
  data_unavailable: 'Data absent', out_of_scope: 'Out of scope', error: 'Error',
};

export default function Observability({ initialUsage, initialEvals }: {
  initialUsage: Usage | null;
  initialEvals: EvalReport | null;
}) {
  const [usage, setUsage] = useState<Usage | null>(initialUsage);
  const [evals, setEvals] = useState<EvalReport | null>(initialEvals);
  const [error, setError] = useState<string | null>(null);
  // Only show skeletons when the server had nothing to give us.
  const [loading, setLoading] = useState(initialUsage === null);

  const load = useCallback(async () => {
    try {
      const [u, e] = await Promise.all([getUsage(), getEvaluations()]);
      setUsage(u); setEvals(e); setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 10_000);
    return () => clearInterval(t);
  }, [load]);

  if (loading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-24" />)}
      </div>
    );
  }

  if (error) {
    return (
      <Panel>
        <Empty icon={<Warning size={24} weight="fill" />} title="Cannot reach the metrics API"
               body={error} />
      </Panel>
    );
  }

  const noRuns = !usage || usage.runs === 0;
  const eff = evals?.efficiency;

  return (
    <div className="space-y-4">
      {/* Live usage ---------------------------------------------------- */}
      <Panel>
        <PanelHead
          title="This session"
          meta={noRuns ? undefined : `${usage!.runs} runs`}
          actions={
            <button onClick={load} aria-label="Refresh metrics"
              className="flex items-center gap-1.5 rounded-sm border border-line px-2 py-1
                         text-[11.5px] text-muted transition-colors hover:text-ink">
              <ArrowsClockwise size={12} weight="bold" aria-hidden /> Refresh
            </button>
          }
        />
        {noRuns ? (
          <Empty icon={<ChartBar size={24} />} title="No runs recorded yet"
                 body="Ask a question and the token spend, latency and model mix for it will appear here." />
        ) : (
          <>
            <div className="grid divide-y divide-line sm:grid-cols-2 sm:divide-y-0
                            lg:grid-cols-4 [&>*]:border-line sm:[&>*:not(:first-child)]:border-l">
              <Stat label="Tokens per run" value={compactNumber(usage!.avg_tokens_per_run)}
                    hint={`${compactNumber(usage!.total_tokens)} total`} />
              <Stat label="Cost per run" value={`$${usage!.avg_cost_per_run_usd.toFixed(6)}`}
                    hint={`$${usage!.total_cost_usd.toFixed(4)} total`} />
              <Stat label="Latency p95" value={ms(usage!.latency_p95_ms)}
                    hint={`p50 ${ms(usage!.latency_p50_ms)}`}
                    tone={usage!.latency_p95_ms > 3000 ? 'warning' : 'good'} />
              <Stat label="LLM calls per run" value={usage!.llm_calls_per_run.toFixed(2)}
                    hint="two is the happy path" />
            </div>

            <div className="grid gap-4 border-t border-line p-3.5 lg:grid-cols-2">
              <div className="space-y-2.5">
                <h3 className="flex items-center gap-1.5 text-[12.5px] font-medium">
                  <Cpu size={14} weight="fill" aria-hidden className="text-muted" />
                  Model tier mix
                </h3>
                <CompositionBar
                  parts={Object.entries(usage!.tier_calls)
                    .sort((a, b) => b[1] - a[1])
                    .map(([k, v]) => ({ label: TIER_LABEL[k] ?? k, value: v }))}
                />
                <p className="text-[11.5px] leading-5 text-muted">
                  Escalation rate {pct(usage!.escalation_rate)}. The small model is the
                  default; a larger one is used only after a measured failure, never on a
                  guess about difficulty.
                </p>
              </div>

              <div className="space-y-2.5">
                <h3 className="flex items-center gap-1.5 text-[12.5px] font-medium">
                  <Gauge size={14} weight="fill" aria-hidden className="text-muted" />
                  Response states
                </h3>
                <CompositionBar
                  parts={Object.entries(usage!.states)
                    .sort((a, b) => b[1] - a[1])
                    .map(([k, v]) => ({ label: STATE_LABEL[k] ?? k, value: v }))}
                />
                <p className="text-[11.5px] leading-5 text-muted">
                  Refusals are a feature. A question the data cannot support should land
                  outside &ldquo;answered&rdquo;.
                </p>
              </div>
            </div>
          </>
        )}
      </Panel>

      {/* Evaluation ---------------------------------------------------- */}
      {evals?.available ? (
        <>
          {evals.planner === 'stub' && (
            <div className="flex items-start gap-2.5 rounded border border-warning/40
                            bg-warning/[.07] px-3.5 py-3">
              <Warning size={15} weight="fill" aria-hidden className="mt-[2px] shrink-0 text-warning" />
              <div>
                <p className="text-[12.5px] font-medium">
                  These scores were produced by the offline stub planner
                </p>
                <p className="mt-0.5 max-w-[76ch] text-[12px] leading-5 text-ink-2">
                  They measure the deterministic pipeline: entity resolution, date handling,
                  compilation, verification and grounding. They are not a measure of
                  natural-language accuracy. Re-run with a live model for that.
                </p>
              </div>
            </div>
          )}

          <Panel>
            <PanelHead title="Golden set evaluation"
              meta={`${evals.questions} questions, ${evals.turns} turns · ${evals.generated_at?.replace('T', ' ')}`}
              actions={
                <StatusPill kind={(evals.grounding_rate ?? 0) >= 1 ? 'good' : 'warning'}>
                  Grounding {pct(evals.grounding_rate ?? 0, 0)}
                </StatusPill>
              } />
            <div className="grid divide-y divide-line sm:grid-cols-2 sm:divide-y-0
                            lg:grid-cols-4 [&>*]:border-line sm:[&>*:not(:first-child)]:border-l">
              <Stat label="Overall" value={pct(evals.overall_accuracy ?? 0, 1)}
                    hint="all checks passed" />
              <Stat label="Numeric accuracy" value={pct(evals.numeric_accuracy ?? 0, 1)}
                    hint="vs. independent computation"
                    tone={(evals.numeric_accuracy ?? 0) >= 1 ? 'good' : 'warning'} />
              <Stat label="Hallucination free" value={pct(evals.hallucination_free_rate ?? 0, 0)}
                    hint="no unverified figures"
                    tone={(evals.hallucination_free_rate ?? 0) >= 1 ? 'good' : 'critical'} />
              <Stat label="Vendor resolution" value={pct(evals.vendor_resolution_accuracy ?? 0, 1)}
                    hint="correct entity chosen" />
            </div>
          </Panel>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartFrame title="Accuracy by question category"
              hint="One measure across categories, so colour carries magnitude and nothing else.">
              <BarSeries horizontal height={330}
                format={(n: number) => `${Math.round(n * 100)}%`}
                data={Object.entries(evals.by_category ?? {})
                  .sort((a, b) => b[1].accuracy - a[1].accuracy)
                  .map(([k, v]) => ({ label: k.replace(/_/g, ' '), value: v.accuracy }))} />
            </ChartFrame>

            <div className="space-y-4">
              <Panel>
                <PanelHead title="Efficiency on the golden set" />
                <div className="grid grid-cols-2 divide-x divide-line">
                  <Stat label="Tokens per turn" value={compactNumber(eff?.avg_tokens_per_turn ?? 0)} />
                  <Stat label="Escalation rate" value={pct(eff?.escalation_rate ?? 0, 1)}
                        hint="small model handled the rest" />
                </div>
                <div className="grid grid-cols-2 divide-x divide-line border-t border-line">
                  <Stat label="Latency p50" value={ms(eff?.latency_p50_ms ?? 0)} />
                  <Stat label="Latency p95" value={ms(eff?.latency_p95_ms ?? 0)} />
                </div>
              </Panel>

              <Panel>
                <PanelHead title="Grounding guarantees" />
                <ul className="divide-y divide-line-soft">
                  {[
                    ['Verification pass rate', evals.verification_pass_rate ?? 0,
                     'Blocking checks veto an answer entirely'],
                    ['Grounding rate', evals.grounding_rate ?? 0,
                     'Every answer carries an evidence package'],
                    ['State accuracy', evals.state_accuracy ?? 0,
                     'Answer, clarify, absent, or out of scope'],
                  ].map(([label, value, hint]) => (
                    <li key={String(label)} className="flex items-center gap-3 px-3.5 py-2.5">
                      {(value as number) >= 1
                        ? <CheckCircle size={15} weight="fill" aria-hidden className="shrink-0 text-good" />
                        : <Warning size={15} weight="fill" aria-hidden className="shrink-0 text-warning" />}
                      <div className="min-w-0">
                        <p className="text-[12.5px]">{label as string}</p>
                        <p className="text-[11.5px] leading-4 text-muted">{hint as string}</p>
                      </div>
                      <p className="num ml-auto font-mono text-[13px]">{pct(value as number, 0)}</p>
                    </li>
                  ))}
                </ul>
              </Panel>
            </div>
          </div>
        </>
      ) : (
        <Panel>
          <PanelHead title="Golden set evaluation" />
          <Empty icon={<ShieldCheck size={24} />} title="No evaluation report yet"
                 body={evals?.hint ?? 'Run scripts/run_evaluation.py to measure accuracy, grounding and efficiency against the 64-question golden set.'} />
        </Panel>
      )}
    </div>
  );
}
