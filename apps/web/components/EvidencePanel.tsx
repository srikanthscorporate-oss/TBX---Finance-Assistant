'use client';

import { useState } from 'react';
import { CheckCircle, Warning, WarningOctagon } from '@phosphor-icons/react';
import type { Evidence, EvidenceRecord } from '@/lib/types';
import { StatusPill } from './ui';

const TABS = ['Checks', 'Facts', 'Query', 'Records'] as const;
type Tab = (typeof TABS)[number];

/** Columns that may be shown, in display order; ids and free text stay out of the table. */
const RECORD_COLUMNS: Record<string, { label: string; align?: 'right'; mono?: boolean }> = {
  transaction_date:            { label: 'Date', mono: true },
  transaction_type:            { label: 'Type' },
  amount_formatted:            { label: 'Amount', align: 'right', mono: true },
  counterparty:                { label: 'Counterparty' },
  channel:                     { label: 'Channel', mono: true },
  account:                     { label: 'Account', mono: true },
  bank:                        { label: 'Bank' },
  reference:                   { label: 'Reference', mono: true },
  utr:                         { label: 'UTR', mono: true },
  program_id:                  { label: 'Program', mono: true },
  available_balance_formatted: { label: 'Available balance', align: 'right', mono: true },
};

const FACT_LABELS: Record<string, string> = {
  total: 'Total', count: 'Transactions', record_count: 'Records matched', shown_total: 'Total of rows shown',
  shown_count: 'Rows shown', top_value: 'Largest group', top_label: 'Largest group name',
  group_count: 'Groups', balance_total: 'Available balance', amount: 'Amount', txn_date: 'Transaction date',
  counterparty: 'Counterparty', channel: 'Channel', account: 'Account', txn_type: 'Transaction type',
};

export const ENTITY_LABELS: Record<string, string> = {
  counterparty: 'Counterparty', account: 'Account', bank: 'Bank', channel: 'Channel',
  transaction_type: 'Transaction type', reference: 'Reference', reference_kind: 'Reference kind',
  entity_id: 'Entity',
};

function cell(r: EvidenceRecord, col: string): string {
  const v = r[col];
  if (v == null || v === '') return '-';
  return String(v);
}

function confidenceKind(band: string) {
  return band === 'high' ? 'good' : band === 'medium' ? 'warning' : 'critical';
}

export default function EvidencePanel({ evidence }: { evidence: Evidence }) {
  const [tab, setTab] = useState<Tab>('Checks');
  const checks = evidence.verification.checks;
  const passed = checks.filter(c => c.passed).length;
  const notes = checks.filter(c => !c.passed);
  const conf = evidence.confidence;
  const columns = evidence.record_columns.filter(c => c in RECORD_COLUMNS);
  const entities = Object.entries(evidence.entities_resolved).filter(([, v]) => v);

  return (
    <div className="mt-3 overflow-hidden rounded border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-2">
        <StatusPill kind={notes.some(n => n.severity === 'blocking') ? 'critical' : 'good'}>
          Verified {passed} of {checks.length}
        </StatusPill>
        {conf && (
          <StatusPill kind={confidenceKind(conf.band) as 'good' | 'warning' | 'critical'}>
            {conf.band} confidence {Math.round(conf.score * 100)}%
          </StatusPill>
        )}
        <div className="ml-auto flex gap-0.5" role="tablist">
          {TABS.map(t => (
            <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
              className={`rounded-sm px-2 py-1 text-[11.5px] transition-colors
                ${tab === t ? 'bg-raised text-ink' : 'text-muted hover:text-ink'}`}>
              {t}
            </button>
          ))}
        </div>
      </div>

      <div className="px-3.5 py-3 text-[12px]">
        {tab === 'Checks' && (
          <ul className="space-y-1.5">
            {checks.map(c => {
              const Icon = c.passed ? CheckCircle : c.severity === 'warning' ? Warning : WarningOctagon;
              const tone = c.passed ? 'text-good' : c.severity === 'warning' ? 'text-warning' : 'text-critical';
              return (
                <li key={c.name} className="flex items-start gap-2">
                  <Icon size={13} weight="fill" aria-hidden className={`mt-[3px] shrink-0 ${tone}`} />
                  <span className="text-ink-2">{c.name.replace(/_/g, ' ')}</span>
                  {c.detail && (
                    <span className="num ml-auto pl-4 text-right font-mono text-[11.5px] text-muted">
                      {c.detail}
                    </span>
                  )}
                </li>
              );
            })}
            {conf?.reasons.length ? (
              <li className="mt-2 border-t border-line-soft pt-2 text-[11.5px] leading-5 text-muted">
                {conf.reasons.join('. ')}.
              </li>
            ) : null}
          </ul>
        )}

        {tab === 'Facts' && (
          <div className="space-y-3">
            <p className="leading-5 text-muted">
              Every figure in the answer is one of these computed values; the model only cites them.
            </p>
            <dl className="grid grid-cols-[minmax(0,auto)_1fr] gap-x-4 gap-y-1">
              {evidence.facts.map(f => (
                <div key={f.key} className="contents">
                  <dt className="text-muted" title={f.key}>{FACT_LABELS[f.key] ?? f.key.replace(/_/g, ' ')}</dt>
                  <dd className="num font-mono text-[11.5px] text-ink-2">
                    {f.formatted}
                    {f.sql_expression && <span className="ml-2 text-muted">{f.sql_expression}</span>}
                  </dd>
                </div>
              ))}
            </dl>
            {entities.length > 0 && (
              <dl className="grid grid-cols-[minmax(0,auto)_1fr] gap-x-4 gap-y-1 border-t border-line-soft pt-2">
                {entities.map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-muted">{ENTITY_LABELS[k] ?? k.replace(/_/g, ' ')}</dt>
                    <dd className="num font-mono text-[11.5px] text-ink-2">{String(v)}</dd>
                  </div>
                ))}
              </dl>
            )}
            {evidence.resolved_period && (
              <p className="num font-mono text-[11.5px] text-muted">
                {evidence.resolved_period}
                {evidence.resolved_start && evidence.resolved_end ? ` (${evidence.resolved_start} to ${evidence.resolved_end})` : ''}
              </p>
            )}
          </div>
        )}

        {tab === 'Query' && (
          <div className="space-y-2.5">
            <p className="leading-5 text-muted">
              Values are bound by the database, never pasted into the statement.
            </p>
            <pre className="whitespace-pre-wrap break-all rounded-sm border border-line-soft bg-raised p-2.5
                            font-mono text-[11px] leading-5 text-ink-2">{evidence.sql}</pre>
            {Object.keys(evidence.sql_params).length > 0 && (
              <dl className="grid grid-cols-[minmax(0,auto)_1fr] gap-x-4 gap-y-1">
                {Object.entries(evidence.sql_params).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="font-mono text-[11.5px] text-muted">{k}</dt>
                    <dd className="num font-mono text-[11.5px] text-ink-2">{v}</dd>
                  </div>
                ))}
              </dl>
            )}
            <p className="num font-mono text-[11.5px] text-muted">
              {evidence.query_duration_ms} ms over {evidence.total_record_count.toLocaleString()} transactions
              {evidence.dataset_version ? `, dataset ${evidence.dataset_version}` : ''}
            </p>
          </div>
        )}

        {tab === 'Records' && (
          evidence.records.length && columns.length ? (
            <div className="max-h-96 overflow-auto">
              <table className="w-full whitespace-nowrap">
                <caption className="sr-only">Records behind this answer</caption>
                <thead className="sticky top-0 bg-surface">
                  <tr className="border-b border-line text-muted">
                    {columns.map(c => (
                      <th key={c} scope="col"
                          className={`px-2 py-1.5 font-medium first:pl-0 last:pr-0 ${RECORD_COLUMNS[c].align === 'right' ? 'text-right' : 'text-left'}`}>
                        {RECORD_COLUMNS[c].label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {evidence.records.map((r, i) => (
                    <tr key={String(r.transaction_id ?? r.account_id ?? i)} className="border-b border-line-soft last:border-0">
                      {columns.map(c => (
                        <td key={c}
                            className={`px-2 py-1.5 first:pl-0 last:pr-0 ${RECORD_COLUMNS[c].align === 'right' ? 'num text-right' : ''} ${
                              RECORD_COLUMNS[c].mono ? 'num font-mono text-[11px]' : ''} ${c === 'reference' || c === 'utr' || c === 'transaction_date' ? 'text-muted' : ''}`}>
                          {cell(r, c)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="num mt-2 font-mono text-[11px] text-muted">
                {evidence.records.length.toLocaleString()} of {evidence.total_record_count.toLocaleString()} shown. Accounts are masked.
              </p>
            </div>
          ) : evidence.sample_records.length ? (
            <table className="w-full">
              <caption className="sr-only">Sample of the underlying transaction records</caption>
              <thead>
                <tr className="border-b border-line text-muted">
                  <th scope="col" className="py-1.5 text-left font-medium">Transaction</th>
                  <th scope="col" className="py-1.5 text-left font-medium">Date</th>
                  <th scope="col" className="py-1.5 text-left font-medium">Counterparty</th>
                  <th scope="col" className="py-1.5 text-right font-medium">Amount</th>
                </tr>
              </thead>
              <tbody>
                {evidence.sample_records.map(r => (
                  <tr key={r.record_id} className="border-b border-line-soft last:border-0">
                    <td className="py-1.5 font-mono text-[11px]">{r.record_id}</td>
                    <td className="num py-1.5 font-mono text-[11.5px] text-muted">{r.txn_date}</td>
                    <td className="py-1.5">{r.counterparty ?? '-'}</td>
                    <td className="num py-1.5 text-right font-mono">
                      {r.amount?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="leading-5 text-muted">
              This answer is an aggregate, so no individual transactions were retrieved. Export
              the breakdown or ask to see the transactions behind it.
            </p>
          )
        )}
      </div>
    </div>
  );
}
