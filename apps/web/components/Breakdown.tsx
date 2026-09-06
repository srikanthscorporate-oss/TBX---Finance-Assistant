'use client';

import { useState } from 'react';
import { DownloadSimple } from '@phosphor-icons/react';
import type { BreakdownRow } from '@/lib/types';
import { BarSeries, LineSeries, seqColor } from './charts';
import { compactMoney, fullMoney } from '@/lib/format';

type View = 'Chart' | 'Table';

export default function Breakdown({ rows, chartHint, currency, exportHref }: {
  rows: BreakdownRow[];
  chartHint?: string | null;
  currency?: string | null;
  exportHref?: string;
}) {
  const [view, setView] = useState<View>(rows.length > 1 ? 'Chart' : 'Table');
  if (!rows.length) return null;

  const isTime = chartHint === 'line';
  const data = rows.map(r => ({ label: r.label, value: r.value }));
  const fmtAxis = (n: number) => compactMoney(n, currency);
  const fmtFull = (n: number) => fullMoney(n, currency);

  return (
    <div className="mt-3 overflow-hidden rounded border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-2">
        <p className="num font-mono text-[11.5px] text-muted">{rows.length} rows</p>
        <div className="ml-auto flex items-center gap-1.5">
          {rows.length > 1 && (
            <div className="flex gap-0.5" role="tablist">
              {(['Chart', 'Table'] as const).map(v => (
                <button key={v} role="tab" aria-selected={view === v} onClick={() => setView(v)}
                  className={`rounded-sm px-2 py-1 text-[11.5px] transition-colors
                    ${view === v ? 'bg-raised text-ink' : 'text-muted hover:text-ink'}`}>
                  {v}
                </button>
              ))}
            </div>
          )}
          {exportHref && (
            <a href={exportHref} download
               className="flex items-center gap-1.5 rounded-sm border border-line px-2 py-1
                          text-[11.5px] text-ink-2 transition-colors hover:border-accent hover:text-ink">
              <DownloadSimple size={13} weight="bold" aria-hidden />
              CSV
            </a>
          )}
        </div>
      </div>

      {view === 'Chart' ? (
        <div className="px-1.5 py-3">
          {isTime
            ? <LineSeries data={data} format={fmtAxis} />
            : <BarSeries data={data} format={fmtAxis} horizontal={rows.length > 4} height={Math.max(180, Math.min(rows.length * 26 + 40, 380))} />}
        </div>
      ) : (
        <div className="max-h-80 overflow-auto">
          <table className="w-full text-[12px]">
            <caption className="sr-only">Breakdown of the answer by group</caption>
            <thead className="sticky top-0 bg-surface">
              <tr className="border-b border-line text-muted">
                <th scope="col" className="px-3.5 py-2 text-left font-medium">Group</th>
                <th scope="col" className="px-3.5 py-2 text-right font-medium">Value</th>
                <th scope="col" className="px-3.5 py-2 text-right font-medium">Records</th>
                <th scope="col" className="px-3.5 py-2 text-right font-medium">Share</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.label} className="border-b border-line-soft last:border-0">
                  <td className="px-3.5 py-2">
                    <span className="flex items-center gap-2">
                      <span aria-hidden className="h-2 w-2 shrink-0 rounded-[2px]"
                            style={{ background: seqColor(i, rows.length) }} />
                      {r.label}
                    </span>
                  </td>
                  <td className="num px-3.5 py-2 text-right font-mono">{fmtFull(r.value)}</td>
                  <td className="num px-3.5 py-2 text-right font-mono text-muted">{r.record_count ?? '-'}</td>
                  <td className="num px-3.5 py-2 text-right font-mono text-muted">
                    {r.share_pct != null ? `${r.share_pct}%` : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
