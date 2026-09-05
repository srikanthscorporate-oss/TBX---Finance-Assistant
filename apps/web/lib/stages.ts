import type { AgentEvent } from './types';

/** Folds the raw event stream onto six pipeline stages. */
export const STAGES = [
  { key: 'understand', label: 'Understand',  events: ['run_started', 'scope_checked', 'intent_detected'] },
  { key: 'resolve',    label: 'Resolve',     events: ['entity_resolved', 'dates_resolved'] },
  { key: 'plan',       label: 'Plan',        events: ['plan_validated'] },
  { key: 'query',      label: 'Query',       events: ['tool_started', 'query_executed', 'tool_completed'] },
  { key: 'verify',     label: 'Verify',      events: ['verification_started', 'verification_completed', 'confidence_computed'] },
  { key: 'answer',     label: 'Answer',      events: ['answer_generated', 'run_completed', 'task_completed'] },
] as const;

export type StageKey = (typeof STAGES)[number]['key'];
export type StageStatus = 'pending' | 'active' | 'done' | 'failed' | 'skipped';

export interface StageState {
  key: StageKey;
  label: string;
  status: StageStatus;
  events: AgentEvent[];
  durationMs: number | null;
}

const TERMINAL = new Set([
  'run_completed', 'run_failed', 'clarification_required',
]);

export function buildStages(events: AgentEvent[], running: boolean): StageState[] {
  const byStage = new Map<string, AgentEvent[]>();
  let openStage: string | null = null;
  for (const e of events) {
    const stage = STAGES.find(s => (s.events as readonly string[]).includes(e.type));
    // Fallback and judge events attach to whichever stage was open when they fired.
    const floating = e.type.startsWith('fallback_') || e.type === 'task_created' || e.type === 'tool_completed';
    const key = stage?.key ?? (floating ? (openStage ?? 'understand') : null);
    if (!key) continue;
    if (stage) openStage = stage.key;
    const list = byStage.get(key) ?? [];
    list.push(e);
    byStage.set(key, list);
  }

  const failed = events.some(e => e.type === 'run_failed');
  const stopped = events.some(e => TERMINAL.has(e.type));
  const lastIndex = STAGES.reduce(
    (acc, s, i) => (byStage.has(s.key) ? i : acc), -1);

  // Stages that never started are omitted rather than shown as skipped.
  return STAGES.flatMap((s, i) => {
    const evs = byStage.get(s.key) ?? [];
    if (!evs.length) return [];
    let status: StageStatus;
    if (failed && i === lastIndex) status = 'failed';
    else status = running && i === lastIndex ? 'active' : 'done';
    const first = evs[0], last = evs[evs.length - 1];
    const durationMs = Math.max(0, new Date(last.at).getTime() - new Date(first.at).getTime());
    return [{ key: s.key, label: s.label, status, events: evs, durationMs }];
  });
}

export function stageOf(type: string): string | null {
  return STAGES.find(s => (s.events as readonly string[]).includes(type))?.label ?? null;
}

export function stageDetail(stage: StageState): [string, string][] {
  const out: [string, string][] = [];
  for (const e of stage.events) {
    const d = e.detail ?? {};
    switch (e.type) {
      case 'intent_detected':
        if (d.intent) out.push(['intent', String(d.intent)]);
        if (d.metric) out.push(['metric', String(d.metric)]);
        if (d.group_by && d.group_by !== 'none') out.push(['grouped by', String(d.group_by)]);
        break;
      case 'entity_resolved':
        if (d.counterparty) out.push(['counterparty', d.query && d.query !== d.counterparty ? `${d.query} to ${d.counterparty}` : String(d.counterparty)]);
        if (d.account) out.push(['account', String(d.account)]);
        if (d.match) out.push(['match', String(d.match)]);
        break;
      case 'dates_resolved':
        out.push(['from', String(d.start)]);
        out.push(['to', String(d.end)]);
        break;
      case 'query_executed':
        if (d.duration_ms) out.push(['query time', `${d.duration_ms} ms`]);
        if (typeof d.rows_read === 'number') out.push(['rows read', d.rows_read.toLocaleString()]);
        break;
      case 'verification_completed': {
        const checks = (d.checks as { name: string; passed: boolean }[]) ?? [];
        const passed = checks.filter(c => c.passed).length;
        out.push(['checks passed', `${passed} of ${checks.length}`]);
        break;
      }
      case 'confidence_computed':
        if (typeof d.score === 'number') out.push(['confidence', `${Math.round(d.score * 100)}%`]);
        break;
      case 'scope_checked':
        if (d.reason) out.push(['reason', String(d.reason)]);
        break;
      case 'fallback_started':
        out.push(['retry', String(d.reason ?? d.error ?? 'first attempt rejected')]);
        break;
      case 'fallback_completed':
        out.push(['escalated', e.label]);
        break;
      case 'task_created':
        out.push(['judge', e.label.replace(/^Judge: /, '')]);
        break;
      case 'task_completed':
        out.push(['verdict', e.label.replace(/^Judge: /, '')]);
        break;
      case 'tool_completed':
        out.push(['anomaly', e.label.replace(/^Anomaly check: /, '')]);
        break;
    }
  }
  return out;
}
