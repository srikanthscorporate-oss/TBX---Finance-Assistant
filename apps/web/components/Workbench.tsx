'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUp, CircleNotch, Sparkle } from '@phosphor-icons/react';
import { getDataset, streamChat } from '@/lib/api';
import type { AgentEvent, DatasetInfo, Turn } from '@/lib/types';
import { stageOf } from '@/lib/stages';
import ModelPicker, { AUTO } from './ModelPicker';
import RunPane from './RunPane';
import { Skeleton } from './ui';

const STARTERS = [
  'How much did we spend with Acme Technologies last month?',
  'Which transactions are still unreconciled?',
  'Show me the top vendors last month',
  'What is our reconciliation rate for the last 6 months?',
];

export default function Workbench() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [model, setModel] = useState<string>(AUTO);
  const [dataset, setDataset] = useState<DatasetInfo | null>(null);
  const [datasetError, setDatasetError] = useState<string | null>(null);
  const conversationId = useRef<string | null>(null);
  const feedEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getDataset().then(setDataset).catch(e => setDatasetError(String(e?.message ?? e)));
  }, []);

  useEffect(() => {
    feedEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turns.length]);

  const ask = useCallback(async (question: string, resolvedVendorId?: string) => {
    const q = question.trim();
    if ((!q && !resolvedVendorId) || busy) return;
    setBusy(true);
    setInput('');
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setTurns(t => [...t, { id, question: q, events: [], running: true }]);
    setSelectedId(id);

    // Events arrive in bursts (plan, query and verify can complete within a
    // few ms of each other). Release them one at a time with a minimum dwell,
    // so exactly one stage is ever "running" and each appears as it starts.
    const queue: AgentEvent[] = [];
    let draining = false;
    const DWELL_MS = 320;
    const drain = async () => {
      if (draining) return;
      draining = true;
      while (queue.length) {
        const e = queue.shift()!;
        setTurns(t => t.map(x => (x.id === id ? { ...x, events: [...x.events, e] } : x)));
        const newStage = stageOf(e.type);
        if (newStage) await new Promise(r => setTimeout(r, DWELL_MS));
      }
      draining = false;
    };
    const onEvent = (e: AgentEvent) => { queue.push(e); void drain(); };

    try {
      const res = await streamChat(q, conversationId.current, onEvent, model, resolvedVendorId);
      // Let the last queued stages land before the answer replaces the spinner.
      while (queue.length || draining) await new Promise(r => setTimeout(r, 40));
      conversationId.current = res.conversation_id;
      setTurns(t => t.map(x => (x.id === id ? { ...x, response: res, running: false } : x)));
    } catch (err) {
      setTurns(t => t.map(x => (x.id === id
        ? { ...x, error: err instanceof Error ? err.message : String(err), running: false } : x)));
    } finally {
      setBusy(false);
    }
  }, [busy, model]);

  // The right pane follows the live run, or whichever turn the user selected.
  const active = useMemo(
    () => turns.find(t => t.id === selectedId) ?? turns[turns.length - 1] ?? null,
    [turns, selectedId],
  );

  return (
    <div className="mx-auto grid h-[calc(100dvh-60px)] w-full max-w-[1400px]
                    grid-rows-[minmax(0,1fr)_minmax(0,1fr)] gap-0
                    lg:grid-cols-[minmax(380px,42%)_1fr] lg:grid-rows-1">

      {/* Conversation ---------------------------------------------------- */}
      <section aria-label="Conversation"
        className="flex min-h-0 flex-col border-b border-line lg:border-b-0 lg:border-r">
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
          {datasetError && (
            <p className="mb-4 rounded border border-critical/40 bg-critical/[.07] px-3 py-2.5
                          text-[12.5px] text-critical">
              Cannot reach the financial dataset. {datasetError}
            </p>
          )}

          {turns.length === 0 && !datasetError && (
            <div className="space-y-4">
              <div className="space-y-2">
                <h1 className="text-[18px] font-semibold leading-tight tracking-tight">
                  Ask about spend, payouts and reconciliation.
                </h1>
                <p className="text-[12.5px] leading-6 text-ink-2">
                  Every figure is computed by a database query and verified before you
                  see it. If the data cannot support an answer, I say so instead of
                  estimating.
                </p>
                {dataset ? (
                  <p className="num font-mono text-[11px] text-muted">
                    {dataset.vendor_count} vendors · data ends {dataset.max_date}
                  </p>
                ) : <Skeleton className="h-3.5 w-52" />}
              </div>
              <ul className="space-y-1.5">
                {STARTERS.map(s => (
                  <li key={s}>
                    <button onClick={() => ask(s)} disabled={busy}
                      className="group flex w-full items-start gap-2 rounded border border-line
                                 bg-surface px-3 py-2 text-left text-[12.5px] leading-5 text-ink-2
                                 transition-colors hover:border-accent hover:text-ink disabled:opacity-50">
                      <Sparkle size={13} weight="fill" aria-hidden
                        className="mt-[3px] shrink-0 text-muted group-hover:text-accent" />
                      {s}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="space-y-4">
            {turns.map(turn => {
              const isActive = active?.id === turn.id;
              const said = turn.response?.answer
                ?? turn.response?.message
                ?? turn.response?.clarification?.question;
              return (
                <article key={turn.id}>
                  <button
                    onClick={() => setSelectedId(turn.id)}
                    aria-current={isActive ? 'true' : undefined}
                    className={`w-full rounded border px-3 py-2.5 text-left transition-colors
                      ${isActive ? 'border-accent bg-accent-soft/40' : 'border-line bg-surface hover:border-muted'}`}
                  >
                    <p className="text-[13px] font-medium leading-5">{turn.question}</p>
                    {turn.running && (
                      <p className="mt-2 flex items-center gap-2 text-[11.5px] text-accent" aria-live="polite">
                        <span className="flex gap-1" aria-hidden>
                          <span className="dot h-1.5 w-1.5 rounded-pill bg-accent" />
                          <span className="dot h-1.5 w-1.5 rounded-pill bg-accent [animation-delay:.15s]" />
                          <span className="dot h-1.5 w-1.5 rounded-pill bg-accent [animation-delay:.3s]" />
                        </span>
                        {(() => {
                          const last = [...turn.events].reverse().find(e => stageOf(e.type));
                          const st = last ? stageOf(last.type) : null;
                          return st ? `${st}: ${last!.label}` : 'Starting';
                        })()}
                      </p>
                    )}
                    {said && <p className="mt-1.5 text-[12.5px] leading-5 text-ink-2">{said}</p>}
                    {turn.error && (
                      <p className="mt-1.5 text-[12px] text-critical">{turn.error}</p>
                    )}
                  </button>

                  {turn.response?.clarification?.options?.length ? (
                    <div className={`mt-2 rounded border px-3 py-2.5 ${
                      turn.response.clarification.field === 'guided' ? 'border-line bg-raised' : 'border-warning/40 bg-warning/[.06]'}`}>
                      <p className="text-[11px] font-medium uppercase tracking-wide text-muted">
                        {turn.response.clarification.field === 'vendor_name' && turn.response.state === 'clarification_required'
                          ? 'Which one did you mean?' : turn.response.clarification.question}
                      </p>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {turn.response.clarification.options.map(o => (
                          <button key={o.value} disabled={busy}
                            onClick={() => turn.response!.state === 'clarification_required'
                              ? ask(`${turn.question}  (${o.label})`, o.value)
                              : ask(o.value.startsWith('V') && turn.response!.clarification!.field === 'vendor_name'
                                  ? o.label : (turn.response!.clarification!.field === 'vendor_name'
                                      ? turn.question.replace(/with .+?( last| this| in |$)/, `with ${o.label}$1`) : o.value))}
                            className="rounded-sm border border-line bg-surface px-2.5 py-1.5 text-[12px]
                                       transition-colors hover:border-accent active:scale-[.98]
                                       disabled:opacity-50">
                            {o.label}
                            {o.hint && <span className="ml-1.5 text-muted">{o.hint}</span>}
                          </button>
                        ))}
                      </div>
                      {turn.response.state === 'clarification_required' && (
                        <p className="mt-2 text-[11px] leading-4 text-muted">
                          The question is kept as you wrote it; only the vendor is filled in.
                        </p>
                      )}
                    </div>
                  ) : null}

                  {turn.response?.follow_up_suggestions?.length ? (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {turn.response.follow_up_suggestions.map(s => (
                        <button key={s} onClick={() => ask(s)} disabled={busy}
                          className="rounded-pill border border-line px-2 py-0.5 text-[11.5px] text-muted
                                     transition-colors hover:border-accent hover:text-ink disabled:opacity-50">
                          {s}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </article>
              );
            })}
            <div ref={feedEnd} />
          </div>
        </div>

        <form onSubmit={e => { e.preventDefault(); ask(input); }}
              className="border-t border-line bg-bg px-4 py-3">
          <div className="flex items-end gap-2">
            <label htmlFor="q" className="sr-only">Your question</label>
            <textarea id="q" value={input} rows={2} disabled={busy}
              onChange={e => {
                setInput(e.target.value);
                // Grow with content, up to about eight lines, then scroll.
                e.target.style.height = 'auto';
                e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`;
              }}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(input); }
              }}
              placeholder="Ask about spend, payouts or reconciliation. Shift+Enter for a new line."
              className="min-h-[64px] flex-1 resize-none rounded border border-line bg-surface px-3 py-2.5
                         text-[13px] leading-5 text-ink outline-none transition-colors
                         placeholder:text-muted focus:border-accent disabled:opacity-60" />
            <ModelPicker value={model} onChange={setModel} disabled={busy} />
            <button type="submit" disabled={busy || !input.trim()} aria-label="Send question"
              className="grid h-[42px] w-[42px] place-items-center rounded bg-accent text-accent-ink
                         transition-transform active:scale-[.97] disabled:opacity-40">
              {busy ? <CircleNotch size={16} weight="bold" aria-hidden className="spin" />
                    : <ArrowUp size={16} weight="bold" aria-hidden />}
            </button>
          </div>
        </form>
      </section>

      {/* Live operations -------------------------------------------------- */}
      {/* The pane itself clips sideways overflow, in every state, so no child
          can ever widen the page. */}
      <section aria-label="Run details" aria-live="polite"
               className="min-h-0 overflow-x-hidden bg-surface [overflow-wrap:anywhere]">
        <RunPane turn={active} dataset={dataset} />
      </section>
    </div>
  );
}
