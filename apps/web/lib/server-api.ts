import 'server-only';
import type { EvalReport, Usage } from './types';

/**
 * Server-side fetch for the first paint.
 *
 * The browser talks to nginx on a relative path; the server component runs
 * inside the container and reaches the API directly. Rendering the first
 * snapshot on the server means the dashboard arrives with real numbers rather
 * than a skeleton that flashes on every load.
 */
const INTERNAL = process.env.INTERNAL_API_BASE ?? 'http://api:8000';

async function get<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${INTERNAL}${path}`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    });
    return r.ok ? ((await r.json()) as T) : null;
  } catch {
    // The page still renders; the client refresh will surface any real outage.
    return null;
  }
}

export const getUsageServer = () => get<Usage>('/api/v1/admin/usage');
export const getEvaluationsServer = () => get<EvalReport>('/api/v1/admin/evaluations');
