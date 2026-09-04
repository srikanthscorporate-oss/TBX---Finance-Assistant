'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { CaretDown, Check, Lightning } from '@phosphor-icons/react';
import type { CatalogModel, ModelCatalog } from '@/lib/types';
import { getModels } from '@/lib/api';

export const AUTO = 'auto';
const STORAGE_KEY = 'tbx-model';
const PROVIDER_ORDER = ['groq', 'openrouter', 'sarvam'] as const;
const PROVIDER_LABEL: Record<string, string> = { groq: 'Groq', openrouter: 'OpenRouter', sarvam: 'Sarvam AI' };

/**
 * A custom listbox rather than a native select: grouped by provider, free
 * models only (the API already filters), a fixed max height that scrolls, and
 * keyboard navigation. Auto stays first and is the recommended default.
 */
export default function ModelPicker({ value, onChange, disabled }: {
  value: string; onChange: (id: string) => void; disabled?: boolean;
}) {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getModels().then(cat => {
      setCatalog(cat);
      // Restore the stored choice only if it is still a listed, available model.
      try {
        const s = localStorage.getItem(STORAGE_KEY);
        const ok = s === AUTO || cat.models.some(m => m.id === s && m.listed && m.available);
        if (s && ok) onChange(s); else if (s) localStorage.removeItem(STORAGE_KEY);
      } catch { /* ignore */ }
    }).catch(() => setCatalog(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  // Free models grouped by provider, in a fixed order. Nothing paid is served.
  const groups = useMemo(() => {
    const listed = (catalog?.models ?? []).filter(m => m.listed);
    return PROVIDER_ORDER
      .map(p => ({ provider: p, label: PROVIDER_LABEL[p], models: listed.filter(m => m.provider === p) }))
      .filter(g => g.models.length > 0);
  }, [catalog]);

  // Sarvam shows as a group even before its key lands, so the user sees it.
  const pendingSarvam = (catalog?.unlisted ?? []).filter(u => u.id.includes('sarvam'));

  const flat = useMemo(() => [AUTO, ...groups.flatMap(g => g.models.filter(m => m.available).map(m => m.id))], [groups]);
  const primary = catalog?.models.find(m => m.id === catalog?.auto.primary);
  const current = catalog?.models.find(m => m.id === value);

  const pick = (id: string) => {
    onChange(id); setOpen(false);
    try { localStorage.setItem(STORAGE_KEY, id); } catch { /* ignore */ }
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (!open && (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setOpen(true); return; }
    if (!open) return;
    if (e.key === 'Escape') setOpen(false);
    if (e.key === 'ArrowDown') { e.preventDefault(); setCursor(c => Math.min(c + 1, flat.length - 1)); }
    if (e.key === 'ArrowUp') { e.preventDefault(); setCursor(c => Math.max(c - 1, 0)); }
    if (e.key === 'Enter') { e.preventDefault(); pick(flat[cursor]); }
  };

  const label = value === AUTO ? `Auto${primary ? ` (${primary.label})` : ''}` : (current?.label ?? value);

  return (
    <div ref={root} className="relative shrink-0">
      <button type="button" disabled={disabled} onClick={() => setOpen(o => !o)} onKeyDown={onKey}
        aria-haspopup="listbox" aria-expanded={open} aria-label={`Model: ${label}`}
        className="flex h-[42px] max-w-[210px] items-center gap-2 rounded border border-line bg-surface px-2.5
                   font-mono text-[11.5px] text-ink-2 transition-colors hover:border-muted
                   focus:border-accent disabled:cursor-not-allowed disabled:opacity-60">
        <Lightning size={13} weight={value === AUTO ? 'fill' : 'regular'} aria-hidden
                   className={value === AUTO ? 'text-accent' : 'text-muted'} />
        <span className="truncate">{label}</span>
        <CaretDown size={12} weight="bold" aria-hidden className={`ml-auto shrink-0 text-muted transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div role="listbox" aria-label="Choose a model" tabIndex={-1} onKeyDown={onKey}
          className="absolute bottom-[calc(100%+6px)] right-0 z-30 w-[300px] max-h-[320px] overflow-y-auto
                     rounded border border-line bg-surface py-1 shadow-lg shadow-black/10">
          <Option id={AUTO} active={value === AUTO} focused={flat[cursor] === AUTO} onPick={pick}
            title={`Auto${primary ? ` (${primary.label} first)` : ''}`}
            sub="Smallest verified model, then a compliant alternate. Recommended." icon />

          {groups.map(g => (
            <div key={g.provider}>
              <p className="sticky top-0 bg-surface px-3 pb-1 pt-2 text-[10.5px] uppercase tracking-wide text-muted">
                {g.label}
                <span className="ml-1.5 normal-case tracking-normal">{g.models.length} free</span>
              </p>
              {g.models.map(m => (
                <Option key={m.id} id={m.id} active={value === m.id} focused={flat[cursor] === m.id}
                  onPick={pick} disabled={!m.available} title={m.label}
                  sub={`${m.size_label}${m.verified ? '' : ', unverified'}${m.available ? '' : ', needs API key'}`} />
              ))}
            </div>
          ))}

          {pendingSarvam.length > 0 && !groups.find(g => g.provider === 'sarvam') && (
            <div>
              <p className="sticky top-0 bg-surface px-3 pb-1 pt-2 text-[10.5px] uppercase tracking-wide text-muted">Sarvam AI</p>
              {pendingSarvam.map(u => (
                <Option key={u.id} id={u.id} active={false} focused={false} onPick={() => {}} disabled
                        title={u.label} sub="activates when SARVAM_API_KEY is set" />
              ))}
            </div>
          )}

          <p className="border-t border-line-soft px-3 pb-1.5 pt-2 text-[10.5px] leading-4 text-muted">
            Only free models within the {catalog?.limit_b ?? 20}B ceiling are listed.
          </p>
        </div>
      )}
    </div>
  );
}

function Option({ id, title, sub, active, focused, disabled, onPick, icon }: {
  id: string; title: string; sub?: string; active: boolean; focused: boolean;
  disabled?: boolean; onPick: (id: string) => void; icon?: boolean;
}) {
  return (
    <button type="button" role="option" aria-selected={active} disabled={disabled}
      onClick={() => onPick(id)}
      className={`flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors
        ${focused ? 'bg-raised' : ''} ${disabled ? 'cursor-not-allowed opacity-45' : 'hover:bg-raised'}`}>
      <span className="mt-[3px] w-3.5 shrink-0 text-accent">
        {active ? <Check size={13} weight="bold" aria-hidden /> : icon ? <Lightning size={13} weight="fill" aria-hidden /> : null}
      </span>
      <span className="min-w-0">
        <span className="block truncate text-[12.5px] text-ink">{title}</span>
        {sub && <span className="block text-[11px] leading-4 text-muted">{sub}</span>}
      </span>
    </button>
  );
}
