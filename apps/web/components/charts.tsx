'use client';

/**
 * Chart primitives.
 *
 * Colour is assigned by the job it does, not by taste:
 *   - one measure across categories  -> the sequential green ramp (magnitude)
 *   - distinct entities              -> the categorical slots, capped at three
 * Both palettes were validated with the palette checker in both light and dark
 * against these exact surfaces. Do not substitute a hue without re-running it.
 */

import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import type { ReactNode } from 'react';

export const SEQ = ['var(--seq-1)', 'var(--seq-2)', 'var(--seq-3)',
                    'var(--seq-4)', 'var(--seq-5)', 'var(--seq-6)'];
export const CAT = ['var(--cat-1)', 'var(--cat-2)', 'var(--cat-3)'];

/** Darkest step for the largest value, so magnitude reads as ink weight. */
export function seqColor(index: number, total: number): string {
  if (total <= 1) return SEQ[4];
  const t = index / Math.max(total - 1, 1);
  return SEQ[Math.min(SEQ.length - 1, Math.round((1 - t) * (SEQ.length - 1)))];
}

const AXIS = { fontSize: 11, fill: 'var(--muted)' } as const;

function TooltipBox({ active, payload, label, format }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-sm border border-line bg-surface px-2.5 py-1.5 shadow-sm">
      <p className="text-[11.5px] text-ink">{label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} className="num font-mono text-[12px] text-ink-2">
          {format ? format(p.value) : p.value}
        </p>
      ))}
    </div>
  );
}

export function BarSeries({ data, format, height = 200, horizontal = false }: {
  data: { label: string; value: number }[];
  format?: (n: number) => string;
  height?: number;
  horizontal?: boolean;
}) {
  const shown = data.slice(0, 20);
  if (horizontal) {
    return (
      <div style={{ height }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={shown} layout="vertical" margin={{ top: 4, right: 44, bottom: 4, left: 4 }}>
            <CartesianGrid stroke="var(--line-soft)" horizontal={false} />
            <XAxis type="number" tickFormatter={format} tick={AXIS} tickLine={false} axisLine={false} />
            <YAxis type="category" dataKey="label" width={116} tick={AXIS}
                   tickLine={false} axisLine={{ stroke: 'var(--line)' }} />
            <Tooltip cursor={{ fill: 'var(--raised)' }} content={<TooltipBox format={format} />} />
            {/* 4px rounded data-end, square against the baseline. */}
            <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={13}>
              {shown.map((_, i) => (
                <Cell key={i} fill={seqColor(i, shown.length)} stroke="var(--surface)" strokeWidth={2} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={shown} margin={{ top: 8, right: 8, bottom: 4, left: 4 }}>
          <CartesianGrid stroke="var(--line-soft)" vertical={false} />
          <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={{ stroke: 'var(--line)' }}
                 interval={0} angle={shown.length > 6 ? -32 : 0}
                 textAnchor={shown.length > 6 ? 'end' : 'middle'} height={shown.length > 6 ? 62 : 26} />
          <YAxis tickFormatter={format} width={62} tick={AXIS} tickLine={false} axisLine={false} />
          <Tooltip cursor={{ fill: 'var(--raised)' }} content={<TooltipBox format={format} />} />
          <Bar dataKey="value" radius={[4, 4, 0, 0]}>
            {shown.map((_, i) => (
              <Cell key={i} fill={seqColor(i, shown.length)} stroke="var(--surface)" strokeWidth={2} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function LineSeries({ data, format, height = 200 }: {
  data: { label: string; value: number }[];
  format?: (n: number) => string;
  height?: number;
}) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
          <CartesianGrid stroke="var(--line-soft)" vertical={false} />
          <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={{ stroke: 'var(--line)' }} />
          <YAxis tickFormatter={format} width={62} tick={AXIS} tickLine={false} axisLine={false} />
          <Tooltip content={<TooltipBox format={format} />} />
          <Line type="monotone" dataKey="value" stroke="var(--seq-5)" strokeWidth={2}
                dot={{ r: 3, fill: 'var(--seq-5)', stroke: 'var(--surface)', strokeWidth: 2 }}
                activeDot={{ r: 5 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * Composition of distinct entities. Capped at three slots plus "Other" -- past
 * that the categorical palette cannot stay separable for colourblind readers.
 * Always direct-labelled, so identity never rests on hue alone.
 */
export function CompositionBar({ parts }: {
  parts: { label: string; value: number }[];
}) {
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  const head = parts.slice(0, 3);
  const rest = parts.slice(3);
  const shown = rest.length
    ? [...head, { label: 'Other', value: rest.reduce((a, p) => a + p.value, 0) }]
    : head;

  return (
    <div className="space-y-2.5">
      <div className="flex h-2.5 w-full gap-[2px] overflow-hidden rounded-pill" role="img"
           aria-label={shown.map(p => `${p.label} ${Math.round((p.value / total) * 100)}%`).join(', ')}>
        {shown.map((p, i) => (
          <div key={p.label} style={{
            width: `${(p.value / total) * 100}%`,
            background: i < 3 ? CAT[i] : 'var(--muted)',
          }} />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
        {shown.map((p, i) => (
          <li key={p.label} className="flex items-center gap-1.5 text-[11.5px]">
            <span aria-hidden className="h-2 w-2 shrink-0 rounded-[2px]"
                  style={{ background: i < 3 ? CAT[i] : 'var(--muted)' }} />
            <span className="text-ink-2">{p.label}</span>
            <span className="num font-mono text-muted">
              {Math.round((p.value / total) * 100)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ChartFrame({ title, hint, children, actions }: {
  title: string; hint?: string; children: ReactNode; actions?: ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded border border-line bg-surface">
      <header className="flex items-start gap-3 px-3.5 py-2.5">
        <div className="min-w-0">
          <h3 className="text-[13px] font-medium tracking-tight">{title}</h3>
          {hint && <p className="mt-0.5 text-[11.5px] leading-4 text-muted">{hint}</p>}
        </div>
        {actions && <div className="ml-auto flex shrink-0 items-center gap-1.5">{actions}</div>}
      </header>
      <div className="px-2 pb-3">{children}</div>
    </section>
  );
}
