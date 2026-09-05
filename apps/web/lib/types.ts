// Mirrors apps/api/app/contracts; only what the UI renders.

export type ResponseState =
  | 'answer' | 'clarification_required' | 'data_unavailable' | 'out_of_scope' | 'error';

export type Intent =
  | 'spend_summary' | 'counterparty_spend' | 'account_summary' | 'transaction_lookup'
  | 'reference_lookup' | 'largest_transactions' | 'top_counterparties' | 'channel_breakdown'
  | 'balance' | 'period_comparison' | 'trend' | 'anomaly_scan';
export type Metric = 'sum' | 'count' | 'avg' | 'min' | 'max' | 'median';
export type GroupBy =
  | 'none' | 'counterparty' | 'account' | 'bank' | 'channel' | 'transaction_type'
  | 'day' | 'week' | 'month' | 'quarter' | 'year';
export type TransactionType = 'debit' | 'credit';
export type Channel =
  | 'NEFT' | 'IMPS' | 'UPI' | 'FT' | 'RTGS' | 'CHEQUE' | 'CHARGES' | 'INTEREST' | 'OTHER';
export type ReferenceKind = 'reference' | 'utr';
export type RelativeRange =
  | 'last_month' | 'this_month' | 'last_quarter' | 'this_quarter' | 'last_year' | 'this_year'
  | 'last_7_days' | 'last_30_days' | 'last_90_days' | 'last_6_months' | 'last_12_months'
  | 'month_before_last' | 'today' | 'yesterday' | 'all_time';

export interface DateRange {
  relative?: RelativeRange | null;
  start?: string | null;
  end?: string | null;
  resolved_start?: string | null;
  resolved_end?: string | null;
  resolved_label?: string | null;
}

/** FinanceQueryPlan: the typed plan; entity_id/counterparty/account_id are set server-side. */
export interface FinanceQueryPlan {
  intent: Intent;
  entity_id?: string | null;
  counterparty_name?: string | null;
  counterparty?: string | null;
  account_last4?: string | null;
  account_id?: string | null;
  bank_code?: string | null;
  reference?: string | null;
  reference_kind?: ReferenceKind | null;
  date_range?: DateRange | null;
  compare_to?: DateRange | null;
  transaction_type?: TransactionType | null;
  channel?: Channel | null;
  min_amount?: number | null;
  max_amount?: number | null;
  metric: Metric;
  group_by: GroupBy;
  limit: number;
  order_desc: boolean;
  user_question?: string | null;
}

export type FactKey =
  | 'total' | 'count' | 'record_count' | 'shown_total' | 'shown_count' | 'top_value'
  | 'top_label' | 'group_count' | 'balance_total' | 'amount' | 'txn_date' | 'counterparty'
  | 'channel' | 'account' | 'txn_type';

export interface ComputedFact {
  key: FactKey | string; value: number | string;
  kind: 'money' | 'count' | 'percent' | 'ratio' | 'text' | 'date';
  currency?: string | null; formatted: string;
  sql_expression?: string | null; record_count?: number | null;
}

export interface BreakdownRow {
  label: string; value: number; record_count?: number | null; share_pct?: number | null;
  [extra: string]: unknown;
}

export interface SourceRecordRef {
  table: string; record_id: string;
  txn_date?: string | null; counterparty?: string | null; amount?: number | null;
}

/** A detail row: transaction records or, for balance, account records. Account is masked. */
export interface TransactionRecord {
  transaction_date?: string; transaction_type?: TransactionType; amount_formatted?: string;
  amount?: number; counterparty?: string | null; channel?: Channel | string; account?: string;
  bank?: string; reference?: string | null; utr?: string | null; description?: string;
  transaction_id?: string;
}
export interface BalanceRecord {
  account?: string; bank?: string; program_id?: number | string;
  available_balance_formatted?: string; account_id?: string;
}
export type EvidenceRecord = (TransactionRecord & BalanceRecord) & Record<string, unknown>;

export type VerificationCheckName =
  | 'date_range_present' | 'date_range_resolved' | 'window_within_dataset'
  | 'counterparty_resolved' | 'account_resolved' | 'records_returned'
  | 'single_transaction_type' | 'aggregate_matches_breakdown' | 'spend_non_negative'
  | 'result_complete' | 'anomaly_callout';

export interface VerificationCheck {
  name: VerificationCheckName | string; passed: boolean; detail?: string | null;
  severity: 'blocking' | 'warning';
}

export interface Confidence {
  score: number; band: 'high' | 'medium' | 'low';
  signals: Record<string, number>; reasons: string[];
}

export interface EntitiesResolved {
  counterparty?: string; account?: string; bank?: string; channel?: string;
  transaction_type?: string; reference?: string; reference_kind?: string; entity_id?: string;
}

export interface Evidence {
  evidence_id: string; run_id: string; plan_fingerprint: string;
  facts: ComputedFact[];
  breakdown: BreakdownRow[];
  breakdown_columns: string[];
  sample_records: SourceRecordRef[];
  records: EvidenceRecord[];
  record_columns: string[];
  total_record_count: number;
  resolved_period?: string | null;
  resolved_start?: string | null;
  resolved_end?: string | null;
  currency?: string | null;
  entities_resolved: EntitiesResolved;
  sql?: string | null;
  sql_params: Record<string, string>;
  query_duration_ms?: number | null;
  verification: { checks: VerificationCheck[] };
  confidence?: Confidence | null;
  dataset_version?: string | null;
  created_at?: string;
}

export type ClarificationField = 'counterparty' | 'account' | 'date_range' | 'guided';

export interface ClarificationOption { label: string; value: string; hint?: string | null }

export interface Clarification {
  question: string;
  options: ClarificationOption[];
  field?: ClarificationField | string | null;
}

export interface AssistantResponse {
  run_id: string; conversation_id: string; state: ResponseState;
  answer?: string | null;
  evidence?: Evidence | null;
  plan?: FinanceQueryPlan | null;
  chart_hint?: string | null;
  clarification?: Clarification | null;
  message?: string | null;
  supported_capabilities: string[];
  follow_up_suggestions: string[];
  duration_ms?: number | null;
  model_usage: { tier: string; model: string; purpose: string;
                 prompt_tokens: number; completion_tokens: number; ok: boolean;
                 duration_ms?: number }[];
  created_at?: string;
}

/** Body of POST /api/v1/chat and /api/v1/chat/stream. */
export interface ChatRequest {
  message: string;
  conversation_id: string | null;
  resolved_value: string | null;
  resolved_field: string | null;
  entity_id: string | null;
  model: string;
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
  dataset_version: string; min_date: string; max_date: string; currency: string;
  account_count: number; counterparty_count: number; entity_count: number;
  banks: Record<string, string>;
}

export interface EntityInfo { entity_id: string; accounts: number; default: boolean }

export interface AccountInfo {
  account_id: string; entity_id: string; account: string; bank_code: string;
  bank_name: string; program_id: number | string; available_balance: number;
}

export interface CounterpartyInfo { name: string; transactions: number; channel: string }

export interface TransactionsPage { rows: EvidenceRecord[]; count: number; duration_ms: number | null }

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
  counterparty_resolution_accuracy?: number;
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

/* ---- Data Source (bring-your-own MySQL endpoint) ------------------------- */

export interface SourceColumn { name: string; type: string; nullable: boolean }
export interface SourceTable { name: string; rows: number; columns: SourceColumn[] }
export interface SourcePreview {
  table: string; columns: string[]; rows: Record<string, string | number | boolean | null>[];
}
export interface SourceTableMapping {
  canonical: 'bank' | 'account' | 'transaction';
  source_table: string | null;
  rows: number;
  columns: Record<string, string>;
  defaulted: string[];
  missing_required: string[];
  usable: boolean;
  derive_type_from_sign: boolean;
}
export interface SourceMapping {
  tables: SourceTableMapping[];
  unmapped_tables: string[];
  ready: boolean;
  problems: string[];
}
export interface SourceTarget { host: string; port: number; database: string; user: string }

export interface ValidateResult {
  status: 'data_available' | 'empty' | 'unreachable';
  connected: boolean;
  error?: string;
  token?: string;
  target: SourceTarget;
  table_count?: number;
  total_rows?: number;
  tables?: SourceTable[];
  preview?: SourcePreview;
  mapping?: SourceMapping;
  can_initialize?: boolean;
}

export interface IngestProgress {
  state: 'idle' | 'running' | 'loaded' | 'ready' | 'failed';
  step: string;
  busy: boolean;
  rows_loaded: Record<string, number>;
  rows_expected: Record<string, number>;
  percent: number;
  error: string | null;
  dataset_version: string | null;
  started_at: string | null;
  finished_at: string | null;
  warnings: string[];
}

export interface SourceStatus {
  progress: IngestProgress;
  active_source: SourceTarget | null;
  dataset: {
    dataset_version: string; min_date: string; max_date: string;
    accounts: number; counterparties: number; entities: number;
  } | null;
  chat_ready: boolean;
}
