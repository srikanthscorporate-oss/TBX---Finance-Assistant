'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowRight, ArrowsClockwise, CheckCircle, CircleNotch, Database, LinkSimple, Plugs, WarningOctagon,
} from '@phosphor-icons/react';
import {
  getSourceStatus, initializeSource, resetSource, validateSource, type ConnectionForm,
} from '@/lib/api';
import type { IngestProgress, SourceStatus, SourceTableMapping, ValidateResult } from '@/lib/types';
import { Panel, PanelHead, StatusPill } from './ui';

const EMPTY_FORM: ConnectionForm = { endpoint: '', port: '', database: '', user: '', password: '' };

/** How long the success panel stays up before the chatbot opens. */
const REDIRECT_MS = 2500;

/** Fields the endpoint link can carry on its own (`mysql://user:pass@host:3306/db`). */
function linkLooksComplete(link: string): boolean {
  const m = link.trim().match(/^(?:jdbc:)?(?:mysql:\/\/)?([^:@/\s]+):([^@\s]+)@([^:/\s]+)(?::(\d+))?\/([^/\s?]+)/);
  return Boolean(m);
}

function Field({ id, label, value, onChange, type = 'text', placeholder, required, autoComplete, mono }: {
  id: keyof ConnectionForm; label: string; value: string; onChange: (v: string) => void;
  type?: string; placeholder?: string; required?: boolean; autoComplete?: string; mono?: boolean;
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={`src-${id}`} className="block text-[11px] uppercase tracking-wide text-muted">
        {label}{required && <span className="ml-0.5 text-critical" aria-hidden>*</span>}
      </label>
      <input id={`src-${id}`} type={type} value={value} placeholder={placeholder}
        autoComplete={autoComplete ?? 'off'} spellCheck={false}
        onChange={e => onChange(e.target.value)}
        className={`w-full rounded border border-line bg-surface px-3 py-2 text-[13px] leading-5 text-ink
                    outline-none transition-colors placeholder:text-muted focus:border-accent
                    ${mono ? 'font-mono text-[12px]' : ''}`} />
    </div>
  );
}

function MappingRow({ m }: { m: SourceTableMapping }) {
  const required = m.canonical !== 'bank';
  return (
    <tr className="border-b border-line-soft align-top last:border-0">
      <td className="px-3.5 py-2 font-mono text-[12px]">{m.canonical}
        {!required && <span className="ml-1.5 text-[10px] uppercase tracking-wide text-muted">optional</span>}
      </td>
      <td className="px-3.5 py-2 font-mono text-[12px]">
        {m.source_table ?? <span className="text-muted">not found</span>}
        {m.source_table && <span className="ml-2 text-[11px] text-muted">{m.rows.toLocaleString()} rows</span>}
      </td>
      <td className="px-3.5 py-2 text-[12px]">
        {m.usable
          ? <StatusPill kind="good">mapped</StatusPill>
          : required
            ? <StatusPill kind="critical">missing {m.missing_required.join(', ')}</StatusPill>
            : <StatusPill kind="info">names fall back to codes</StatusPill>}
        {m.usable && m.defaulted.length > 0 && (
          <p className="mt-1 text-[11px] leading-4 text-muted">
            defaulted: {m.defaulted.join(', ')}{m.derive_type_from_sign ? '; direction from amount sign' : ''}
          </p>
        )}
      </td>
    </tr>
  );
}

function PreviewTable({ result, onPick }: { result: ValidateResult; onPick: (t: string) => void }) {
  const preview = result.preview;
  if (!preview) return null;
  return (
    <Panel>
      <PanelHead title="Data preview"
        meta={<>
          <span className="font-mono">{preview.table}</span> · first {preview.rows.length} rows
        </>}
        actions={
          <label className="flex items-center gap-1.5 text-[12px] text-muted">
            Table
            <select value={preview.table} onChange={e => onPick(e.target.value)}
              className="rounded border border-line bg-surface px-2 py-1 font-mono text-[12px] text-ink">
              {(result.tables ?? []).map(t => (
                <option key={t.name} value={t.name}>{t.name} ({t.rows.toLocaleString()})</option>
              ))}
            </select>
          </label>
        } />
      <div className="max-h-[420px] overflow-auto">
        <table className="w-full text-[12px]">
          <caption className="sr-only">Preview of {preview.table}</caption>
          <thead className="sticky top-0 bg-surface">
            <tr className="border-b border-line text-muted">
              {preview.columns.map(c => (
                <th key={c} scope="col" className="whitespace-nowrap px-3.5 py-2 text-left font-medium">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row, i) => (
              <tr key={i} className="border-b border-line-soft last:border-0">
                {preview.columns.map(c => (
                  <td key={c} className="max-w-[28ch] truncate whitespace-nowrap px-3.5 py-1.5 font-mono text-[11px]"
                      title={row[c] == null ? '' : String(row[c])}>
                    {row[c] == null ? <span className="text-muted">null</span> : String(row[c])}
                  </td>
                ))}
              </tr>
            ))}
            {preview.rows.length === 0 && (
              <tr><td colSpan={preview.columns.length} className="px-3.5 py-6 text-center text-muted">
                This table is empty.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function Progress({ p }: { p: IngestProgress }) {
  const tables = ['bank', 'account', 'transaction'] as const;
  return (
    <div className="space-y-3 px-4 py-3">
      <div className="flex items-center gap-2 text-[13px]">
        {p.busy && <CircleNotch size={15} className="spin text-accent" aria-hidden />}
        {p.state === 'ready' && <CheckCircle size={15} weight="fill" className="text-good" aria-hidden />}
        {p.state === 'failed' && <WarningOctagon size={15} weight="fill" className="text-critical" aria-hidden />}
        <span className="capitalize">{p.busy ? p.step : p.state}</span>
        <span className="num ml-auto font-mono text-[12px] text-muted">{p.percent.toFixed(0)}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-pill bg-raised" role="progressbar"
           aria-valuenow={p.percent} aria-valuemin={0} aria-valuemax={100}>
        <div className={`h-full transition-[width] duration-300 ${p.state === 'failed' ? 'bg-critical' : 'bg-accent'}`}
             style={{ width: `${Math.max(2, p.percent)}%` }} />
      </div>
      <dl className="grid grid-cols-3 gap-2 text-[12px]">
        {tables.map(t => (
          <div key={t} className="rounded border border-line-soft px-2.5 py-1.5">
            <dt className="font-mono text-[11px] text-muted">{t}</dt>
            <dd className="num font-mono">
              {(p.rows_loaded[t] ?? 0).toLocaleString()}
              {p.rows_expected[t] != null && <span className="text-muted"> / {p.rows_expected[t].toLocaleString()}</span>}
            </dd>
          </div>
        ))}
      </dl>
      {p.error && <p className="text-[12px] leading-5 text-critical">{p.error}</p>}
      {p.warnings.map(w => <p key={w} className="text-[12px] leading-5 text-warning">{w}</p>)}
    </div>
  );
}

export default function DataSource({ initialStatus }: { initialStatus: SourceStatus | null }) {
  const [form, setForm] = useState<ConnectionForm>(EMPTY_FORM);
  const [validating, setValidating] = useState(false);
  const [result, setResult] = useState<ValidateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<SourceStatus | null>(initialStatus);
  const [starting, setStarting] = useState(false);
  const [redirecting, setRedirecting] = useState(false);
  const [resetting, setResetting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const redirectedRef = useRef(false);
  const router = useRouter();

  const set = (k: keyof ConnectionForm) => (v: string) => setForm(f => ({ ...f, [k]: v }));
  const linkComplete = linkLooksComplete(form.endpoint);
  const canSubmit = Boolean(form.endpoint.trim()) &&
    (linkComplete || Boolean(form.database.trim() && form.user.trim()));

  const validate = useCallback(async (previewTable?: string) => {
    setValidating(true);
    setError(null);
    try {
      const r = await validateSource(form, previewTable);
      setResult(r);
      if (!r.connected) setError(r.error ?? 'endpoint unreachable');
    } catch (e) {
      setResult(null);
      setError((e as Error).message);
    } finally {
      setValidating(false);
    }
  }, [form]);

  /** A link with every field filled in is submitted as soon as it is pasted. */
  useEffect(() => {
    if (!linkComplete || result || validating) return;
    const t = setTimeout(() => { void validate(); }, 400);
    return () => clearTimeout(t);
  }, [linkComplete, result, validating, validate]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  const poll = useCallback(() => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const s = await getSourceStatus();
        setStatus(s);
        if (!s.progress.busy) stopPolling();
      } catch { /* keep polling */ }
    }, 1000);
  }, [stopPolling]);

  useEffect(() => {
    if (initialStatus?.progress.busy) poll();
    return stopPolling;
  }, [initialStatus, poll, stopPolling]);

  const start = async () => {
    if (!result?.token) return;
    setStarting(true);
    setError(null);
    try {
      const r = await initializeSource(result.token);
      setStatus(s => s
        ? { ...s, progress: r.status }
        : { progress: r.status, active_source: null, active_database: '', bundled: true,
            dataset: null, chat_ready: false });
      poll();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  };

  const useBundled = async () => {
    setResetting(true);
    setError(null);
    try {
      await resetSource();
      setStatus(await getSourceStatus());
      redirectedRef.current = false;
      setRedirecting(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setResetting(false);
    }
  };

  const progress = status?.progress;
  const running = Boolean(progress?.busy);
  const dataAvailable = result?.status === 'data_available';

  /* A finished initialisation hands the user straight to the chatbot, which is now
     answering from their endpoint. Fires once; the link in the panel is the fallback
     if the navigation is blocked. */
  useEffect(() => {
    if (progress?.state !== 'ready' || redirectedRef.current) return;
    redirectedRef.current = true;
    setRedirecting(true);
    const t = setTimeout(() => router.push('/'), REDIRECT_MS);
    return () => clearTimeout(t);
  }, [progress?.state, router]);

  return (
    <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
      {/* ---- Left: connection form + initialise ---------------------------- */}
      <div className="space-y-4">
        <Panel>
          <PanelHead title="MySQL endpoint" meta="read-only connection" />
          <form className="space-y-3 px-4 py-3"
                onSubmit={e => { e.preventDefault(); void validate(); }}>
            <Field id="endpoint" label="Endpoint link" value={form.endpoint} onChange={set('endpoint')} mono
              required placeholder="mysql://user:password@host:3306/database" />
            <p className="-mt-1 text-[11px] leading-4 text-muted">
              A link carrying user, password, port and database connects on its own. Otherwise give
              the host here and fill in the rest below; these fields override the link.
            </p>
            <div className="grid grid-cols-[1fr_88px] gap-3">
              <Field id="database" label="Database" value={form.database} onChange={set('database')} mono
                placeholder="finance" required={!linkComplete} />
              <Field id="port" label="Port" value={form.port} onChange={set('port')} mono placeholder="3306" />
            </div>
            <Field id="user" label="User" value={form.user} onChange={set('user')} autoComplete="username"
              placeholder="readonly_user" required={!linkComplete} />
            <Field id="password" label="Password" value={form.password} onChange={set('password')}
              type="password" autoComplete="current-password" />
            <div className="flex items-center gap-2 pt-1">
              <button type="submit" disabled={validating || running || !canSubmit}
                className="inline-flex h-[36px] items-center gap-1.5 rounded border border-line bg-raised px-3
                           text-[13px] font-medium text-ink transition-colors hover:border-accent
                           disabled:opacity-40">
                {validating ? <CircleNotch size={14} className="spin" aria-hidden /> : <Plugs size={14} aria-hidden />}
                {validating ? 'Connecting…' : 'Connect'}
              </button>
              {result && (
                result.status === 'data_available'
                  ? <StatusPill kind="good">Data Available</StatusPill>
                  : result.status === 'empty'
                    ? <StatusPill kind="warning">Connected, no data</StatusPill>
                    : <StatusPill kind="critical">Unreachable</StatusPill>
              )}
            </div>
            {error && (
              <p role="alert" className="rounded border border-critical/40 bg-critical/10 px-3 py-2 text-[12px] leading-5 text-critical">
                {error}
              </p>
            )}
          </form>
        </Panel>

        <Panel>
          <PanelHead title="Initialize" meta={running ? 'in progress' : dataAvailable ? 'ready' : 'validate first'} />
          <div className="space-y-3 px-4 py-3">
            <p className="text-[12px] leading-5 text-ink-2">
              Loads the endpoint&rsquo;s tables into the assistant&rsquo;s verified store and makes them the
              dataset the chatbot answers from. They go into a <strong>separate database</strong>, so the
              bundled demo dataset stays intact and you can switch back at any time. Sensitive fields are
              encrypted on the way in; the endpoint itself is only ever read.
            </p>
            {result?.mapping && !result.mapping.ready && (
              <ul className="space-y-1 text-[12px] leading-5 text-critical">
                {result.mapping.problems.map(p => <li key={p}>{p}</li>)}
              </ul>
            )}
            <button type="button" onClick={start}
              disabled={!dataAvailable || !result?.can_initialize || starting || running}
              className="inline-flex h-[38px] w-full items-center justify-center gap-2 rounded bg-accent px-3
                         text-[13px] font-medium text-accent-ink transition-transform active:scale-[.99]
                         disabled:opacity-40">
              {starting || running ? <CircleNotch size={15} className="spin" aria-hidden /> : <Database size={15} aria-hidden />}
              {running ? 'Initializing…' : 'Start Initializing'}
            </button>
          </div>
          {progress && progress.state !== 'idle' && <Progress p={progress} />}
          {progress?.state === 'ready' && (
            <div className="border-t border-line px-4 py-3">
              <p className="text-[12px] leading-5 text-ink-2">
                The chatbot is now answering from{' '}
                <span className="font-mono">{status?.active_source?.database ?? 'the new source'}</span>
                {status?.dataset && <> ({status.dataset.min_date} → {status.dataset.max_date},{' '}
                  {status.dataset.accounts.toLocaleString()} accounts)</>}.
              </p>
              <Link href="/"
                className="mt-2 inline-flex items-center gap-1.5 text-[13px] font-medium text-accent hover:underline">
                {redirecting ? 'Opening the chatbot…' : 'Start asking questions'} <ArrowRight size={14} aria-hidden />
              </Link>
            </div>
          )}
        </Panel>

        {status && (
          <Panel>
            <PanelHead title="Active dataset"
              meta={status.bundled ? 'bundled demo data' : 'your endpoint'} />
            <div className="space-y-2 px-4 py-3">
              <p className="font-mono text-[12px] text-ink-2">
                {status.active_source
                  ? `${status.active_source.user}@${status.active_source.host}:${status.active_source.port}/${status.active_source.database}`
                  : 'bundled dataset'}
                {status.active_database && <span className="text-muted"> &rarr; {status.active_database}</span>}
              </p>
              {status.dataset && (
                <p className="text-[11px] leading-4 text-muted">
                  {status.dataset.dataset_version} · {status.dataset.min_date} &rarr; {status.dataset.max_date} ·{' '}
                  {status.dataset.accounts.toLocaleString()} accounts
                </p>
              )}
              {!status.bundled && (
                <button type="button" onClick={useBundled} disabled={resetting || running}
                  className="inline-flex h-[30px] items-center gap-1.5 rounded border border-line bg-raised px-2.5
                             text-[12px] text-ink transition-colors hover:border-accent disabled:opacity-40">
                  {resetting ? <CircleNotch size={13} className="spin" aria-hidden /> : <ArrowsClockwise size={13} aria-hidden />}
                  Use the bundled dataset
                </button>
              )}
            </div>
          </Panel>
        )}
      </div>

      {/* ---- Right: what is in the endpoint ------------------------------- */}
      <div className="space-y-4">
        {!result && (
          <Panel>
            <div className="flex flex-col items-center gap-2 px-6 py-16 text-center">
              <LinkSimple size={28} className="text-muted" aria-hidden />
              <p className="text-[13px] font-medium">Connect a MySQL endpoint</p>
              <p className="max-w-[52ch] text-[12px] leading-5 text-muted">
                Enter the link on the left. The tables it exposes will appear here with a live preview,
                and you can then make it the assistant&rsquo;s dataset.
              </p>
            </div>
          </Panel>
        )}

        {result?.connected && (
          <>
            <div className="flex items-center gap-2 rounded border border-good/30 bg-good/10 px-3.5 py-2.5 text-[13px]">
              <CheckCircle size={16} weight="fill" className="text-good shrink-0" aria-hidden />
              <span>
                Database connected &mdash; <span className="font-mono">{result.target.database}</span> on{' '}
                <span className="font-mono">{result.target.host}:{result.target.port}</span>, {result.table_count}{' '}
                table{result.table_count === 1 ? '' : 's'} available.
              </span>
            </div>
            <Panel>
              <PanelHead title="Tables"
                meta={<>
                  <span className="font-mono">{result.target.database}</span> on{' '}
                  <span className="font-mono">{result.target.host}:{result.target.port}</span> ·{' '}
                  {result.table_count} table{result.table_count === 1 ? '' : 's'} ·{' '}
                  {(result.total_rows ?? 0).toLocaleString()} rows
                </>} />
              <div className="overflow-x-auto">
                <table className="w-full text-[12px]">
                  <caption className="sr-only">Tables in the source database</caption>
                  <thead>
                    <tr className="border-b border-line text-muted">
                      <th scope="col" className="px-3.5 py-2 text-left font-medium">Table</th>
                      <th scope="col" className="px-3.5 py-2 text-right font-medium">Rows</th>
                      <th scope="col" className="px-3.5 py-2 text-left font-medium">Columns</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(result.tables ?? []).map(t => (
                      <tr key={t.name} className="border-b border-line-soft last:border-0">
                        <td className="px-3.5 py-2 font-mono">
                          <button type="button" onClick={() => void validate(t.name)}
                                  className="hover:text-accent hover:underline">{t.name}</button>
                        </td>
                        <td className="num px-3.5 py-2 text-right font-mono">{t.rows.toLocaleString()}</td>
                        <td className="px-3.5 py-2 text-[11px] leading-5 text-muted">
                          {t.columns.map(c => c.name).join(', ')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>

            <PreviewTable result={result} onPick={t => void validate(t)} />

            {result.mapping && (
              <Panel>
                <PanelHead title="How it maps to the assistant"
                  meta={result.mapping.ready ? 'ready to initialize' : 'cannot initialize yet'} />
                <div className="overflow-x-auto">
                  <table className="w-full text-[12px]">
                    <caption className="sr-only">Mapping from source tables to the canonical schema</caption>
                    <thead>
                      <tr className="border-b border-line text-muted">
                        <th scope="col" className="px-3.5 py-2 text-left font-medium">Assistant table</th>
                        <th scope="col" className="px-3.5 py-2 text-left font-medium">Source table</th>
                        <th scope="col" className="px-3.5 py-2 text-left font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.mapping.tables.map(m => <MappingRow key={m.canonical} m={m} />)}
                    </tbody>
                  </table>
                </div>
                {result.mapping.unmapped_tables.length > 0 && (
                  <p className="border-t border-line px-3.5 py-2 text-[11px] leading-4 text-muted">
                    Not used: {result.mapping.unmapped_tables.join(', ')}
                  </p>
                )}
              </Panel>
            )}
          </>
        )}
      </div>
    </div>
  );
}
