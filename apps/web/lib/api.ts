import type { AgentEvent, AssistantResponse, DatasetInfo, EvalReport, JudgeSummary, ModelCatalog, Usage } from './types';

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? '';

export async function getDataset(): Promise<DatasetInfo> {
  const r = await fetch(`${BASE}/api/v1/dataset`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`dataset unavailable (${r.status})`);
  return r.json();
}

/**
 * Stream one question. Agent events arrive as they happen so the timeline
 * reflects real work rather than a canned animation; the final payload carries
 * the verified answer.
 */
export async function streamChat(
  message: string,
  conversationId: string | null,
  onEvent: (e: AgentEvent) => void,
  model: string = 'auto',
  resolvedVendorId?: string,
  signal?: AbortSignal,
): Promise<AssistantResponse> {
  const res = await fetch(`${BASE}/api/v1/chat/stream`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      message, conversation_id: conversationId, model,
      resolved_vendor_id: resolvedVendorId ?? null,
    }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`request failed (${res.status})`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let final: AssistantResponse | null = null;

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    let idx: number;
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const eventLine = frame.match(/^event: (.+)$/m);
      const dataLine = frame.match(/^data: (.*)$/m);
      if (!eventLine || !dataLine) continue;
      const payload = JSON.parse(dataLine[1]);
      if (eventLine[1] === 'final') final = payload as AssistantResponse;
      else onEvent(payload as AgentEvent);
    }
  }

  if (!final) throw new Error('stream ended without a final answer');
  return final;
}

export function exportUrl(params: Record<string, string | undefined>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) qs.set(k, v);
  return `${BASE}/api/v1/export.csv?${qs.toString()}`;
}

export async function getUsage(): Promise<Usage> {
  const r = await fetch(`${BASE}/api/v1/admin/usage`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`usage unavailable (${r.status})`);
  return r.json();
}

export async function getEvaluations(): Promise<EvalReport> {
  const r = await fetch(`${BASE}/api/v1/admin/evaluations`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`evaluations unavailable (${r.status})`);
  return r.json();
}

export async function getModels(): Promise<ModelCatalog> {
  const r = await fetch(`${BASE}/api/v1/models`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`model catalog unavailable (${r.status})`);
  return r.json();
}

export async function getJudge(): Promise<JudgeSummary> {
  const r = await fetch(`${BASE}/api/v1/admin/judge`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`judge unavailable (${r.status})`);
  return r.json();
}
