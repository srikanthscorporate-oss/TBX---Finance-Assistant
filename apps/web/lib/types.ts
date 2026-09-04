// Mirrors apps/api/app/contracts. Kept narrow: only what the UI renders.

export type ResponseState =
  | 'answer' | 'clarification_required' | 'data_unavailable' | 'out_of_scope' | 'error';

export interface ComputedFact {
  key: string; value: number | string; kind: string;
  currency?: string | null; formatted: string;
  sql_expression?: string | null; record_count?: number | null;
}

export interface BreakdownRow {
  label: string; value: number; record_count?: number | null; share_pct?: number | null;
}

export interface VerificationCheck {
  name: string; passed: boolean; detail?: string | null; severity: 'blocking' | 'warning';
}

export interface Confidence {
  score: number; band: 'high' | 'medium' | 'low';
  signals: Record<string, number>; reasons: string[];
}

export interface Evidence {
  evidence_id: string; run_id: string;
  facts: ComputedFact[];
  breakdown: BreakdownRow[];
  sample_records: { record_id: string; txn_date?: string | null; amount?: number | null }[];
  total_record_count: number;
  resolved_period?: string | null;
  resolved_start?: string | null;
  resolved_end?: string | null;
  currency?: string | null;
  entities_resolved: Record<string, string>;
  sql?: string | null;
  sql_params: Record<string, string>;
  query_duration_ms?: number | null;
  verification: { checks: VerificationCheck[] };
  confidence?: Confidence | null;
  dataset_version?: string | null;
}

export interface ClarificationOption { label: string; value: string; hint?: string | null }

export interface AssistantResponse {
  run_id: string; conversation_id: string; state: ResponseState;
  answer?: string | null;
  evidence?: Evidence | null;
  plan?: Record<string, unknown> | null;
  chart_hint?: string | null;
  clarification?: { question: string; field?: string | null; options: ClarificationOption[] } | null;
  message?: string | null;
  supported_capabilities: string[];
  follow_up_suggestions: string[];
  duration_ms?: number | null;
  model_usage: { tier: string; model: string; purpose: string;
                 prompt_tokens: number; completion_tokens: number; ok: boolean }[];
}

export interface AgentEvent {
  type: string; run_id: string; seq: number; label: string;
  detail: Record<string, unknown>; at: string;
}

export interface Turn {
  id: string;
  question: string;
  events: AgentEvent[];
  response?: AssistantResponse;
  error?: string;
  running: boolean;
}

export interface DatasetInfo {
  dataset_version: string; min_date: string; max_date: string;
  currency: string; vendor_count: number; categories: string[];
}

export interface Usage {
  runs: number;
  total_tokens: number;
  avg_tokens_per_run: number;
  total_cost_usd: number;
  avg_cost_per_run_usd: number;
  llm_calls_per_run: number;
  escalation_rate: number;
  small_model_share: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
  states: Record<string, number>;
  tier_calls: Record<string, number>;
  time_split_ms?: { llm: number; query: number; other: number };
  recent?: RecentRun[];
}

export interface RecentRun {
  run_id: string; state: string; duration_ms: number | null;
  llm_ms: number; query_ms: number; tokens: number;
  model: string | null; switched: boolean; at: string;
}

export interface EvalCategory { total: number; passed: number; accuracy: number }

export interface EvalReport {
  available: boolean;
  hint?: string;
  generated_at?: string;
  planner?: string;
  caveat?: string;
  questions?: number;
  turns?: number;
  overall_accuracy?: number;
  state_accuracy?: number;
  intent_accuracy?: number;
  vendor_resolution_accuracy?: number;
  numeric_accuracy?: number;
  grounding_rate?: number;
  verification_pass_rate?: number;
  hallucination_free_rate?: number;
  rate_limited_calls?: number;
  throttled?: boolean;
  last_clean?: EvalReport | null;
  efficiency?: {
    avg_llm_calls_per_turn: number;
    avg_tokens_per_turn: number;
    total_tokens: number;
    escalation_rate: number;
    latency_p50_ms: number;
    latency_p95_ms: number;
  };
  by_category?: Record<string, EvalCategory>;
}

export interface CatalogModel {
  id: string; label: string; provider: string;
  params_b: number; active_params_b: number | null; size_label: string;
  free: boolean; verified: boolean; available: boolean; listed: boolean;
  over_limit: boolean; refused?: boolean; size_known?: boolean; discovered?: boolean;
  note: string;
}

export interface ModelCatalog {
  limit_b: number;
  auto: { primary: string | null; alternate: string | null; policy: string };
  models: CatalogModel[];
  over_ceiling?: CatalogModel[];
  unlisted: { id: string; label: string; reason: string }[];
  excluded: { id: string; reason: string }[];
}

export interface JudgeSummary {
  enabled: boolean;
  runs_scored: number;
  avg_score: number | null;
  cache: { plan: number; answer: number; miss: number; hit_rate: number };
  models: Record<string, { plan_validity: number | null; samples: number; breaker_open_s: number; trips_last_hour: number; quality_open?: boolean; available?: boolean }>;
  recent: { score: number; state: string; tokens: number; duration_ms: number; model: string | null;
            switched: boolean; notes: string[]; cache_hit: string | null; run_id: string }[];
}
