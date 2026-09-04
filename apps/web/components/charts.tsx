'use client';

/**
 * Chart primitives.
 *
 * Colour is assigned by the job it does, never by taste:
 *   one measure across categories -> the sequential green ramp (magnitude)
 *   distinct entities            -> the categorical slots, capped at three
 *   state                        -> the fixed status tokens, with a label
 * Every colour is a token, validated in both themes. "Pop" comes from motion,
 * hierarchy and richer marks: same-hue gradients, draw-in animation, direct
 * value labels, ring sweeps and gauges. Never from a new hue or a glow.
 */

import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import { useEffect, useId, useState, type ReactNode } from 'react';
import { useReducedMotion } from '@/lib/motion';

export const SEQ = ['var(--seq-1)', 'var(--seq-2)', 'var(--seq-3)', 'var(--seq-4)', 'var(--seq-5)', 'var(--seq-6)'];
export const CAT = ['var(--cat-1)', 'var(--cat-2)', 'var(--cat-3)'];

/** Darkest step for the largest value, so magnitude reads as ink weight. */
export function seqColor(index: number, total: number): string {
  if (total <= 1) return SEQ[4];
  const t = index / Math.max(total - 1, 1);
  return SEQ[Math.min(SEQ.length - 1, Math.round((1 - t) * (SEQ.length - 1)))];
}

const AXIS = { fontSize: 11, fill: 'var(--muted)', fontFamily: 'var(--font-geist-mono)' } as const;
const EASE = 'cubic-bezier(.16,1,.3,1)';

function TooltipBox({ active, payload, label, format }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-sm border border-line bg-surface px-2.5 py-1.5 shadow-md shadow-black/10">
      <p className="text-[11.5px] text-ink">{label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} className="num font-mono text-[12.5px] font-medium text-ink-2">
          {format ? format(p.value) : p.value}
        </p>
      ))}
    </div>
  );
}

/** Same-hue vertical/horizontal gradient: two steps of one ramp, never two hues. */
function SeqGradient({ id, horizontal }: { id: string; horizontal?: boolean }) {
  return (
    <defs>
      <linearGradient id={id} x1="0" y1={horizontal ? '0' : '1'} x2={horizontal ? '1' : '0'} y2="0">
        <stop offset="0%" stopColor="var(--seq-3)" />
        <stop offset="100%" stopColor="var(--seq-5)" />
      </linearGradient>
      <linearGradient id={`${id}-area`} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="var(--seq-4)" stopOpacity="0.55" />
        <stop offset="100%" stopColor="var(--seq-4)" stopOpacity="0.02" />
      </linearGradient>
    </defs>
  );
}

export function BarSeries({ data, format, height = 200, horizontal = false, showValues = true }: {
  data: { label: string; value: number }[];
  format?: (n: number) => string; height?: number; horizontal?: boolean; showValues?: boolean;
}) {
  const shown = data.slice(0, 20);
  const reduced = useReducedMotion();
  const gid = useId().replace(/:/g, '');
  const anim = { isAnimationActive: !reduced, animationDuration: 900, animationEasing: 'ease-out' as const };
  const labelStyle = { fontSize: 11, fill: 'var(--ink-2)', fontFamily: 'var(--font-geist-mono)' };

  if (horizontal) {
    return (
      <div style={{ height }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={shown} layout="vertical" margin={{ top: 4, right: 56, bottom: 4, left: 4 }} barCategoryGap="28%">
            <SeqGradient id={gid} horizontal />
            <CartesianGrid stroke="var(--line-soft)" horizontal={false} strokeDasharray="2 4" />
            <XAxis type="number" tickFormatter={format} tick={AXIS} tickLine={false} axisLine={false} domain={[0, 'dataMax']} />
            <YAxis type="category" dataKey="label" width={118} tick={AXIS} tickLine={false} axisLine={{ stroke: 'var(--line)' }} />
            <Tooltip cursor={{ fill: 'var(--raised)' }} content={<TooltipBox format={format} />} />
            <Bar dataKey="value" radius={[0, 5, 5, 0]} barSize={14} {...anim}>
              {shown.map((_, i) => (
                <Cell key={i} fill={i === 0 ? `url(#${gid})` : seqColor(i, shown.length)}
                      stroke="var(--surface)" strokeWidth={2} />
              ))}
              {showValues && <LabelList dataKey="value" position="right" formatter={format} style={labelStyle} />}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={shown} margin={{ top: 18, right: 8, bottom: 4, left: 4 }} barCategoryGap="24%">
          <SeqGradient id={gid} />
          <CartesianGrid stroke="var(--line-soft)" vertical={false} strokeDasharray="2 4" />
          <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={{ stroke: 'var(--line)' }}
                 interval={0} angle={shown.length > 6 ? -32 : 0}
                 textAnchor={shown.length > 6 ? 'end' : 'middle'} height={shown.length > 6 ? 62 : 26} />
          <YAxis tickFormatter={format} width={62} tick={AXIS} tickLine={false} axisLine={false} />
          <Tooltip cursor={{ fill: 'var(--raised)' }} content={<TooltipBox format={format} />} />
          <Bar dataKey="value" radius={[5, 5, 0, 0]} {...anim}>
            {shown.map((_, i) => (
              <Cell key={i} fill={i === 0 ? `url(#${gid})` : seqColor(i, shown.length)}
                    stroke="var(--surface)" strokeWidth={2} />
            ))}
            {showValues && shown.length <= 12 && <LabelList dataKey="value" position="top" formatter={format} style={labelStyle} />}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Change over time as a line with a soft area beneath it: one series, one hue. */
export function LineSeries({ data, format, height = 200 }: {
  data: { label: string; value: number }[]; format?: (n: number) => string; height?: number;
}) {
  const reduced = useReducedMotion();
  const gid = useId().replace(/:/g, '');
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 10, right: 12, bottom: 4, left: 4 }}>
          <SeqGradient id={gid} />
          <CartesianGrid stroke="var(--line-soft)" vertical={false} strokeDasharray="2 4" />
          <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={{ stroke: 'var(--line)' }} />
          <YAxis tickFormatter={format} width={62} tick={AXIS} tickLine={false} axisLine={false} />
          <Tooltip content={<TooltipBox format={format} />} cursor={{ stroke: 'var(--line)', strokeDasharray: '3 3' }} />
          <Area type="monotone" dataKey="value" stroke="var(--seq-5)" strokeWidth={2.25}
                fill={`url(#${gid}-area)`} isAnimationActive={!reduced} animationDuration={1000}
                dot={{ r: 3, fill: 'var(--seq-5)', stroke: 'var(--surface)', strokeWidth: 2 }}
                activeDot={{ r: 5.5, stroke: 'var(--surface)', strokeWidth: 2 }} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/** A number that has just changed counts up to its value. */
function useCountUp(target: number, ms = 800): number {
  const reduced = useReducedMotion();
  const [v, setV] = useState(reduced ? target : 0);
  useEffect(() => {
    if (reduced) { setV(target); return; }
    let raf = 0; const t0 = performance.now();
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / ms); const e = 1 - Math.pow(1 - k, 3);
      setV(target * e); if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms, reduced]);
  return v;
}

/**
 * Part-to-whole for two or three segments, drawn as a sweep. Capped at three
 * on purpose: beyond that the palette stops being separable for colourblind
 * readers. Status use takes the status tokens with a label in the legend.
 */
export function RingChart({ parts, centre, sub, size = 140, status = false, thickness = 12 }: {
  parts: { label: string; value: number }[];
  centre: string; sub?: string; size?: number; status?: boolean; thickness?: number;
}) {
  const reduced = useReducedMotion();
  const [drawn, setDrawn] = useState(reduced);
  useEffect(() => { const id = requestAnimationFrame(() => setDrawn(true)); return () => cancelAnimationFrame(id); }, []);
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  const r = size / 2 - thickness / 2 - 2, c = size / 2, circ = 2 * Math.PI * r;
  const palette = status ? ['var(--good)', 'var(--critical)', 'var(--warning)'] : CAT;
  let offset = 0;
  const arcs = parts.slice(0, 3).map((p, i) => {
    const frac = p.value / total;
    const dash = Math.max(0, frac * circ - 3);   // 3px surface gap between fills
    const el = (
      <circle key={p.label} cx={c} cy={c} r={r} fill="none" stroke={palette[i]} strokeWidth={thickness}
        strokeLinecap="round"
        strokeDasharray={`${drawn ? dash : 0} ${circ}`}
        strokeDashoffset={-offset * circ}
        transform={`rotate(-90 ${c} ${c})`}
        style={{ transition: reduced ? 'none' : `stroke-dasharray 1.1s ${EASE} ${i * 120}ms` }} />
    );
    offset += frac;
    return el;
  });
  return (
    <div className="flex items-center gap-5">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
           aria-label={parts.map(p => `${p.label} ${Math.round(p.value / total * 100)}%`).join(', ')}>
        <circle cx={c} cy={c} r={r} fill="none" stroke="var(--line-soft)" strokeWidth={thickness} />
        {arcs}
        <text x={c} y={c - 1} textAnchor="middle" fill="var(--ink)" fontSize={size > 130 ? 24 : 17}
              fontWeight={600} fontFamily="var(--font-geist-mono)">{centre}</text>
        {sub && <text x={c} y={c + 17} textAnchor="middle" fill="var(--muted)" fontSize={10.5}>{sub}</text>}
      </svg>
      <ul className="space-y-2">
        {parts.slice(0, 3).map((p, i) => (
          <li key={p.label} className="flex items-center gap-2 text-[12px]">
            <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: palette[i] }} />
            <span className="text-ink-2">{p.label}</span>
            <span className="num ml-auto pl-3 font-mono text-ink">{Math.round(p.value / total * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * A rate as a 270-degree gauge with ticks and a sweeping fill. For a single
 * percentage the gauge reads faster than a ring: the arc's angle IS the value.
 */
export function RadialGauge({ value, label, size = 168, tone = 'seq', caption }: {
  value: number; label: string; size?: number; tone?: 'seq' | 'status'; caption?: string;
}) {
  const reduced = useReducedMotion();
  const shown = useCountUp(Math.max(0, Math.min(1, value)));
  const [drawn, setDrawn] = useState(reduced);
  useEffect(() => { const id = requestAnimationFrame(() => setDrawn(true)); return () => cancelAnimationFrame(id); }, []);
  const gid = useId().replace(/:/g, '');
  const thickness = 14, r = size / 2 - thickness / 2 - 4, c = size / 2;
  const sweep = 270, start = 135;
  const arcLen = (2 * Math.PI * r) * (sweep / 360);
  const filled = arcLen * (drawn ? Math.max(0, Math.min(1, value)) : 0);
  const color = tone === 'status'
    ? (value >= 0.9 ? 'var(--good)' : value >= 0.7 ? 'var(--warning)' : 'var(--critical)')
    : `url(#${gid})`;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(t => {
    const a = ((start + sweep * t) * Math.PI) / 180;
    const ro = r + thickness / 2 + 3, ri = r + thickness / 2 + 8;
    return { x1: c + ro * Math.cos(a), y1: c + ro * Math.sin(a), x2: c + ri * Math.cos(a), y2: c + ri * Math.sin(a) };
  });
  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size * 0.82} viewBox={`0 0 ${size} ${size * 0.82}`} role="img" aria-label={`${label} ${Math.round(value * 100)}%`}>
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--seq-3)" /><stop offset="100%" stopColor="var(--seq-6)" />
          </linearGradient>
        </defs>
        <circle cx={c} cy={c} r={r} fill="none" stroke="var(--line-soft)" strokeWidth={thickness} strokeLinecap="round"
                strokeDasharray={`${arcLen} ${2 * Math.PI * r}`} transform={`rotate(${start} ${c} ${c})`} />
        <circle cx={c} cy={c} r={r} fill="none" stroke={color} strokeWidth={thickness} strokeLinecap="round"
                strokeDasharray={`${filled} ${2 * Math.PI * r}`} transform={`rotate(${start} ${c} ${c})`}
                style={{ transition: reduced ? 'none' : `stroke-dasharray 1.2s ${EASE}` }} />
        {ticks.map((t, i) => <line key={i} {...t} stroke="var(--line)" strokeWidth={1.5} strokeLinecap="round" />)}
        <text x={c} y={c + 4} textAnchor="middle" fill="var(--ink)" fontSize={30} fontWeight={600}
              fontFamily="var(--font-geist-mono)">{Math.round(shown * 100)}%</text>
        <text x={c} y={c + 24} textAnchor="middle" fill="var(--muted)" fontSize={11}>{label}</text>
      </svg>
      {caption && <p className="-mt-1 text-[11px] text-muted">{caption}</p>}
    </div>
  );
}

/**
 * Where the time went: one stacked bar, three phases, labelled inside the
 * segment when there is room. Model (cat-1), database (cat-2), the rest (cat-3).
 */
export function TimingBar({ llm, query, other, height = 14 }: {
  llm: number; query: number; other: number; height?: number;
}) {
  const reduced = useReducedMotion();
  const [drawn, setDrawn] = useState(reduced);
  useEffect(() => { const id = requestAnimationFrame(() => setDrawn(true)); return () => cancelAnimationFrame(id); }, []);
  const total = llm + query + other || 1;
  const segs = [
    { label: 'Model', value: llm, color: CAT[0] },
    { label: 'Database', value: query, color: CAT[1] },
    { label: 'Checks and glue', value: other, color: CAT[2] },
  ];
  const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(2)}s` : `${Math.round(n)}ms`);
  return (
    <div className="space-y-2.5">
      <div className="flex w-full gap-[3px] overflow-hidden rounded-pill" style={{ height }} role="img"
           aria-label={segs.map(s => `${s.label} ${fmt(s.value)}`).join(', ')}>
        {segs.map(s => {
          const pct = (s.value / total) * 100;
          return (
            <div key={s.label} title={`${s.label}: ${fmt(s.value)}`}
                 className="relative flex items-center justify-center overflow-hidden"
                 style={{ width: `${drawn ? pct : 0}%`, background: s.color,
                          transition: reduced ? 'none' : `width 1s ${EASE}` }}>
              {pct > 14 && <span className="num px-1 font-mono text-[10px] font-medium text-white/95">{Math.round(pct)}%</span>}
            </div>
          );
        })}
      </div>
      <ul className="flex flex-wrap gap-x-5 gap-y-1">
        {segs.map(s => (
          <li key={s.label} className="flex items-center gap-1.5 text-[11.5px]">
            <span aria-hidden className="h-2.5 w-2.5 rounded-[3px]" style={{ background: s.color }} />
            <span className="text-ink-2">{s.label}</span>
            <span className="num font-mono text-ink">{fmt(s.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A trend line with a soft area, drawn in. One series: no legend, no axis. */
export function Sparkline({ values, width = 110, height = 32, tone = 'var(--seq-5)' }: {
  values: number[]; width?: number; height?: number; tone?: string;
}) {
  const reduced = useReducedMotion();
  const gid = useId().replace(/:/g, '');
  const [drawn, setDrawn] = useState(reduced);
  useEffect(() => { const id = requestAnimationFrame(() => setDrawn(true)); return () => cancelAnimationFrame(id); }, []);
  if (values.length < 2) return <svg width={width} height={height} aria-hidden />;
  const max = Math.max(...values), min = Math.min(...values), span = max - min || 1;
  const step = width / (values.length - 1);
  const pts = values.map((v, i) => [i * step, height - 4 - ((v - min) / span) * (height - 8)] as const);
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const area = `0,${height} ${line} ${width},${height}`;
  const [lx, ly] = pts[pts.length - 1];
  const len = width * 1.4;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img"
         aria-label={`trend of ${values.length} points, latest ${values[values.length - 1]}`}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={tone} stopOpacity="0.35" /><stop offset="100%" stopColor={tone} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={area} fill={`url(#${gid})`} style={{ opacity: drawn ? 1 : 0, transition: reduced ? 'none' : 'opacity .8s ease .5s' }} />
      <polyline points={line} fill="none" stroke={tone} strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round"
                strokeDasharray={len} strokeDashoffset={drawn ? 0 : len}
                style={{ transition: reduced ? 'none' : `stroke-dashoffset 1s ${EASE}` }} />
      <circle cx={lx} cy={ly} r={2.75} fill={tone} stroke="var(--surface)" strokeWidth={1.5} />
    </svg>
  );
}

/**
 * Confidence signals as a dot matrix: five dots per signal, filled to its
 * score, rows labelled so the shape never rests on colour alone.
 */
export function SignalDots({ signals }: { signals: Record<string, number> }) {
  return (
    <ul className="grid grid-cols-1 gap-y-2 sm:grid-cols-2 sm:gap-x-6">
      {Object.entries(signals).map(([k, v], row) => {
        const filled = Math.round(Math.max(0, Math.min(1, v)) * 5);
        const tone = v >= 0.85 ? 'var(--good)' : v >= 0.6 ? 'var(--warning)' : 'var(--critical)';
        return (
          <li key={k} className="flex items-center gap-2 text-[11.5px]">
            <span className="w-[112px] truncate text-ink-2" title={k}>{k.replace(/_/g, ' ')}</span>
            <span className="flex gap-1" role="img" aria-label={`${k.replace(/_/g, ' ')} ${Math.round(v * 100)}%`}>
              {Array.from({ length: 5 }).map((_, i) => (
                <span key={i} aria-hidden className="rise h-2.5 w-2.5 rounded-pill"
                      style={{ background: i < filled ? tone : 'var(--line)', animationDelay: `${(row * 5 + i) * 25}ms` }} />
              ))}
            </span>
            <span className="num ml-auto font-mono text-ink">{Math.round(v * 100)}%</span>
          </li>
        );
      })}
    </ul>
  );
}

export function CompositionBar({ parts }: { parts: { label: string; value: number }[] }) {
  const reduced = useReducedMotion();
  const [drawn, setDrawn] = useState(reduced);
  useEffect(() => { const id = requestAnimationFrame(() => setDrawn(true)); return () => cancelAnimationFrame(id); }, []);
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  const head = parts.slice(0, 3), rest = parts.slice(3);
  const shown = rest.length ? [...head, { label: 'Other', value: rest.reduce((a, p) => a + p.value, 0) }] : head;
  return (
    <div className="space-y-2.5">
      <div className="flex h-3 w-full gap-[3px] overflow-hidden rounded-pill" role="img"
           aria-label={shown.map(p => `${p.label} ${Math.round((p.value / total) * 100)}%`).join(', ')}>
        {shown.map((p, i) => (
          <div key={p.label} style={{ width: `${drawn ? (p.value / total) * 100 : 0}%`, background: i < 3 ? CAT[i] : 'var(--muted)',
                                    transition: reduced ? 'none' : `width .9s ${EASE} ${i * 80}ms` }} />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
        {shown.map((p, i) => (
          <li key={p.label} className="flex items-center gap-1.5 text-[11.5px]">
            <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: i < 3 ? CAT[i] : 'var(--muted)' }} />
            <span className="text-ink-2">{p.label}</span>
            <span className="num font-mono text-ink">{Math.round((p.value / total) * 100)}%</span>
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
    <section className="overflow-hidden rounded border border-line bg-surface shadow-[inset_0_1px_0_var(--line-soft)]">
      <header className="flex min-h-[44px] items-center gap-3 border-b border-line-soft px-4 py-2">
        <div className="min-w-0">
          <h3 className="text-[13px] font-semibold tracking-tight">{title}</h3>
          {hint && <p className="mt-0.5 text-[11.5px] leading-4 text-muted">{hint}</p>}
        </div>
        {actions && <div className="ml-auto flex shrink-0 items-center gap-1.5">{actions}</div>}
      </header>
      <div className="px-2 pb-3">{children}</div>
    </section>
  );
}
