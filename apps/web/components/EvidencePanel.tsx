'use client';

import { useState } from 'react';
import { CheckCircle, Warning, WarningOctagon } from '@phosphor-icons/react';
import type { Evidence } from '@/lib/types';
import { StatusPill } from './ui';

const TABS = ['Checks', 'Query', 'Records'] as const;
type Tab = (typeof TABS)[number];

function confidenceKind(band: string) {
  return band === 'high' ? 'good' : band === 'medium' ? 'warning' : 'critical';
}

export default function EvidencePanel({ evidence }: { evidence: Evidence }) {
  const [tab, setTab] = useState<Tab>('Checks');
  const checks = evidence.verification.checks;
  const passed = checks.filter(c => c.passed).length;
  const notes = checks.filter(c => !c.passed);
  const conf = evidence.confidence;

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

        {tab === 'Query' && (
          <div className="space-y-2.5">
            <p className="leading-5 text-muted">
              Values are bound by the database, never pasted into the statement.
            </p>
            <pre className="overflow-x-auto rounded-sm border border-line-soft bg-raised p-2.5
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
              {evidence.query_duration_ms} ms over {evidence.total_record_count.toLocaleString()} records
              {evidence.dataset_version ? `, dataset ${evidence.dataset_version}` : ''}
            </p>
          </div>
        )}

        {tab === 'Records' && (
          evidence.sample_records.length ? (
            <table className="w-full">
              <caption className="sr-only">Sample of the underlying transaction records</caption>
              <thead>
                <tr className="border-b border-line text-muted">
                  <th scope="col" className="py-1.5 text-left font-medium">Transaction</th>
                  <th scope="col" className="py-1.5 text-left font-medium">Date</th>
                  <th scope="col" className="py-1.5 text-right font-medium">Amount</th>
                </tr>
              </thead>
              <tbody>
                {evidence.sample_records.map(r => (
                  <tr key={r.record_id} className="border-b border-line-soft last:border-0">
                    <td className="py-1.5 font-mono text-[11px]">{r.record_id}</td>
                    <td className="num py-1.5 font-mono text-[11.5px] text-muted">{r.txn_date}</td>
                    <td className="num py-1.5 text-right font-mono">
                      {r.amount?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="leading-5 text-muted">
              This answer is an aggregate, so no individual rows were retrieved. Export
              the breakdown to inspect the underlying records.
            </p>
          )
        )}
      </div>
    </div>
  );
}
