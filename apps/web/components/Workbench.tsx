'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUp, CircleNotch, Sparkle } from '@phosphor-icons/react';
import { getDataset, streamChat } from '@/lib/api';
import type { AgentEvent, DatasetInfo, Turn } from '@/lib/types';
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

  const ask = useCallback(async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setInput('');
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setTurns(t => [...t, { id, question: q, events: [], running: true }]);
    setSelectedId(id);

    const onEvent = (e: AgentEvent) =>
      setTurns(t => t.map(x => (x.id === id ? { ...x, events: [...x.events, e] } : x)));

    try {
      const res = await streamChat(q, conversationId.current, onEvent);
      conversationId.current = res.conversation_id;
      setTurns(t => t.map(x => (x.id === id ? { ...x, response: res, running: false } : x)));
    } catch (err) {
      setTurns(t => t.map(x => (x.id === id
        ? { ...x, error: err instanceof Error ? err.message : String(err), running: false } : x)));
    } finally {
      setBusy(false);
    }
  }, [busy]);

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
                      <p className="mt-1.5 flex items-center gap-1.5 text-[11.5px] text-accent">
                        <CircleNotch size={12} weight="bold" aria-hidden className="spin" />
                        Working
                      </p>
                    )}
                    {said && <p className="mt-1.5 text-[12.5px] leading-5 text-ink-2">{said}</p>}
                    {turn.error && (
                      <p className="mt-1.5 text-[12px] text-critical">{turn.error}</p>
                    )}
                  </button>

                  {turn.response?.clarification?.options?.length ? (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {turn.response.clarification.options.map(o => (
                        <button key={o.value} disabled={busy}
                          onClick={() => ask(`${turn.question} (${o.label})`)}
                          className="rounded-sm border border-line bg-surface px-2 py-1 text-[11.5px]
                                     transition-colors hover:border-accent disabled:opacity-50">
                          {o.label}
                        </button>
                      ))}
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
          <div className="flex items-center gap-2">
            <label htmlFor="q" className="sr-only">Your question</label>
            <input id="q" value={input} onChange={e => setInput(e.target.value)} disabled={busy}
              placeholder="Ask about spend, payouts or reconciliation"
              className="flex-1 rounded border border-line bg-surface px-3 py-2.5 text-[13px] text-ink
                         outline-none transition-colors placeholder:text-muted
                         focus:border-accent disabled:opacity-60" />
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
      <section aria-label="Run details" aria-live="polite" className="min-h-0 bg-surface">
        <RunPane turn={active} dataset={dataset} />
      </section>
    </div>
  );
}
