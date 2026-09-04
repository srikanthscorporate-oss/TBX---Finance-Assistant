import type { AgentEvent } from './types';

/**
 * The event stream is fine-grained; the operator wants six stages.
 * This folds raw events onto the pipeline's real phases so the right pane can
 * show progress that means something, rather than a scrolling log.
 */
export const STAGES = [
  { key: 'understand', label: 'Understand',  events: ['run_started', 'scope_checked', 'intent_detected'] },
  { key: 'resolve',    label: 'Resolve',     events: ['entity_resolved', 'dates_resolved'] },
  { key: 'plan',       label: 'Plan',        events: ['plan_validated', 'task_created'] },
  { key: 'query',      label: 'Query',       events: ['tool_started', 'query_executed', 'tool_completed'] },
  { key: 'verify',     label: 'Verify',      events: ['verification_started', 'verification_completed', 'confidence_computed'] },
  { key: 'answer',     label: 'Answer',      events: ['answer_generated', 'run_completed'] },
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
    // Fallback and escalation events belong to whichever stage was running when
    // they fired, so attach them there rather than dropping them. Escalation is
    // a headline efficiency signal; it must never disappear from the timeline.
    const key = stage?.key ?? (e.type.startsWith('fallback_') ? openStage : null);
    if (!key) continue;
    if (stage) openStage = stage.key;
    const list = byStage.get(key) ?? [];
    list.push(e);
    byStage.set(key, list);
  }

  const failed = events.some(e => e.type === 'run_failed');
  const stopped = events.some(e => TERMINAL.has(e.type));
  // Which stage is furthest along?
  const lastIndex = STAGES.reduce(
    (acc, s, i) => (byStage.has(s.key) ? i : acc), -1);

  return STAGES.map((s, i) => {
    const evs = byStage.get(s.key) ?? [];
    let status: StageStatus;
    if (failed && i === lastIndex) status = 'failed';
    else if (evs.length) status = running && i === lastIndex ? 'active' : 'done';
    else if (stopped || !running) status = i <= lastIndex ? 'skipped' : 'pending';
    else status = i === lastIndex + 1 ? 'active' : 'pending';

    const first = evs[0], last = evs[evs.length - 1];
    const durationMs = evs.length >= 1 && first && last
      ? Math.max(0, new Date(last.at).getTime() - new Date(first.at).getTime())
      : null;

    return { key: s.key, label: s.label, status, events: evs, durationMs };
  });
}

/** Human-readable facts pulled out of a stage's events, for the detail rows. */
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
        out.push(['vendor', `${d.query} to ${d.vendor_id}`]);
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
    }
  }
  return out;
}
