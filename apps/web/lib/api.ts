import type {
  AccountInfo, AgentEvent, AssistantResponse, ChatRequest, CounterpartyInfo, DatasetInfo,
  EntityInfo, EvalReport, IngestProgress, JudgeSummary, ModelCatalog, SourceStatus,
  TransactionsPage, Usage, ValidateResult,
} from './types';

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? '';

async function getJson<T>(path: string, what: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${what} unavailable (${r.status})`);
  return r.json();
}

function query(params: Record<string, string | number | undefined | null>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v != null && v !== '') qs.set(k, String(v));
  const s = qs.toString();
  return s ? `?${s}` : '';
}

export const getDataset = () => getJson<DatasetInfo>('/api/v1/dataset', 'dataset');
export const getEntities = () => getJson<EntityInfo[]>('/api/v1/entities', 'entities');
export const getAccounts = (entityId?: string) =>
  getJson<AccountInfo[]>(`/api/v1/accounts${query({ entity_id: entityId })}`, 'accounts');
export const getCounterparties = (entityId?: string, limit?: number) =>
  getJson<CounterpartyInfo[]>(`/api/v1/counterparties${query({ entity_id: entityId, limit })}`, 'counterparties');
export const getTransactions = (params: {
  entity_id?: string; counterparty?: string; channel?: string;
  transaction_type?: string; relative?: string; limit?: number;
}) => getJson<TransactionsPage>(`/api/v1/transactions${query(params)}`, 'transactions');

export interface ChatOptions {
  model?: string;
  resolvedValue?: string;
  resolvedField?: string;
  entityId?: string | null;
  signal?: AbortSignal;
}

function chatBody(message: string, conversationId: string | null, o: ChatOptions): ChatRequest {
  return {
    message,
    conversation_id: conversationId,
    resolved_value: o.resolvedValue ?? null,
    resolved_field: o.resolvedField ?? null,
    entity_id: o.entityId ?? null,
    model: o.model ?? 'auto',
  };
}

/** Stream one question; agent events fire as they arrive, the final payload is returned. */
export async function streamChat(
  message: string,
  conversationId: string | null,
  onEvent: (e: AgentEvent) => void,
  options: ChatOptions = {},
): Promise<AssistantResponse> {
  const res = await fetch(`${BASE}/api/v1/chat/stream`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(chatBody(message, conversationId, options)),
    signal: options.signal,
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
  return `${BASE}/api/v1/export.csv${query(params)}`;
}

export const getUsage = () => getJson<Usage>('/api/v1/admin/usage', 'usage');
export const getEvaluations = () => getJson<EvalReport>('/api/v1/admin/evaluations', 'evaluations');
export const getModels = () => getJson<ModelCatalog>('/api/v1/models', 'model catalog');
export const getJudge = () => getJson<JudgeSummary>('/api/v1/admin/judge', 'judge');

/* ---- Data Source --------------------------------------------------------- */

/** The Data Source form. `endpoint` is either a full link or a bare host; the other
 *  fields fill in whatever the link does not carry, and override it when it does. */
export interface ConnectionForm {
  endpoint: string; port: string; database: string; user: string; password: string;
}

async function readError(r: Response): Promise<string> {
  try {
    const body = await r.json();
    if (typeof body?.detail === 'string') return body.detail;
    if (Array.isArray(body?.detail)) return body.detail.map((d: { msg?: string }) => d.msg ?? '').join('; ');
  } catch { /* not JSON */ }
  return `request failed (${r.status})`;
}

export async function validateSource(form: ConnectionForm, previewTable?: string): Promise<ValidateResult> {
  const r = await fetch(`${BASE}/api/v1/sources/validate`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      endpoint: form.endpoint, host: '', port: form.port ? Number(form.port) : null,
      database: form.database, user: form.user, password: form.password,
      preview_table: previewTable ?? null,
    }),
  });
  if (!r.ok) throw new Error(await readError(r));
  return r.json();
}

export async function initializeSource(token: string): Promise<{ started: boolean; status: IngestProgress }> {
  const r = await fetch(`${BASE}/api/v1/sources/initialize`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ token }),
  });
  if (!r.ok) throw new Error(await readError(r));
  return r.json();
}

/** Hand the chatbot back to the bundled dataset; the ingested one is left in place. */
export async function resetSource(): Promise<{ reset: boolean; active_database: string }> {
  const r = await fetch(`${BASE}/api/v1/sources/reset`, { method: 'POST' });
  if (!r.ok) throw new Error(await readError(r));
  return r.json();
}

export async function getSourceStatus(): Promise<SourceStatus> {
  const r = await fetch(`${BASE}/api/v1/sources/status`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`source status unavailable (${r.status})`);
  return r.json();
}

export const HISTORY_CLEARED_EVENT = 'tbx:history-cleared';

/** Forget every conversation and reset the observability counters, server-side and in every open pane. */
export async function clearHistory(): Promise<{ runs: number; conversations: number; redis_keys: number }> {
  const res = await fetch(`${BASE}/api/v1/history/clear`, { method: 'POST' });
  if (!res.ok) throw new Error(`clear history failed: ${res.status}`);
  const out = await res.json();
  window.dispatchEvent(new Event(HISTORY_CLEARED_EVENT));
  return out;
}
