import 'server-only';
import type { EvalReport, JudgeSummary, Usage } from './types';

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

export const getUsageServer = () => get<Usage>('/api/v1/admin/usage');
export const getEvaluationsServer = () => get<EvalReport>('/api/v1/admin/evaluations');
export const getJudgeServer = () => get<JudgeSummary>('/api/v1/admin/judge');
