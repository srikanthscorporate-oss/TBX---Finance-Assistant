import 'server-only';
import type {
  AccountInfo, CounterpartyInfo, DatasetInfo, EntityInfo, EvalReport, JudgeSummary,
  SourceStatus, TransactionsPage, Usage,
} from './types';

// Server components reach the API directly inside the compose network.
const INTERNAL = process.env.INTERNAL_API_BASE ?? 'http://api:8000';

async function get<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${INTERNAL}${path}`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    });
    return r.ok ? ((await r.json()) as T) : null;
  } catch {
    return null;
  }
}

function query(params: Record<string, string | number | undefined | null>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v != null && v !== '') qs.set(k, String(v));
  const s = qs.toString();
  return s ? `?${s}` : '';
}

export const getUsageServer = () => get<Usage>('/api/v1/admin/usage');
export const getEvaluationsServer = () => get<EvalReport>('/api/v1/admin/evaluations');
export const getJudgeServer = () => get<JudgeSummary>('/api/v1/admin/judge');
export const getDatasetServer = () => get<DatasetInfo>('/api/v1/dataset');
export const getSourceStatusServer = () => get<SourceStatus>('/api/v1/sources/status');
export const getEntitiesServer = () => get<EntityInfo[]>('/api/v1/entities');
export const getAccountsServer = (entityId?: string) =>
  get<AccountInfo[]>(`/api/v1/accounts${query({ entity_id: entityId })}`);
export const getCounterpartiesServer = (entityId?: string, limit?: number) =>
  get<CounterpartyInfo[]>(`/api/v1/counterparties${query({ entity_id: entityId, limit })}`);
export const getTransactionsServer = (params: {
  entity_id?: string; counterparty?: string; channel?: string;
  transaction_type?: string; relative?: string; limit?: number;
}) => get<TransactionsPage>(`/api/v1/transactions${query(params)}`);
