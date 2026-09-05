'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import { ChartLineUp, ChatCircleDots, Plugs, Trash } from '@phosphor-icons/react';
import ThemeToggle from './ThemeToggle';
import { clearHistory } from '@/lib/api';

const NAV = [
  { href: '/', label: 'Ask', Icon: ChatCircleDots },
  { href: '/observability', label: 'Observability', Icon: ChartLineUp },
  { href: '/datasource', label: 'Data Source', Icon: Plugs },
];

export default function Shell({ children, meta }: {
  children: React.ReactNode; meta?: React.ReactNode;
}) {
  const pathname = usePathname();
  return (
    <div className="min-h-[100dvh]">
      <header className="sticky top-0 z-20 border-b border-line bg-bg/85 backdrop-blur">
        <div className="mx-auto flex h-[60px] w-full max-w-[1400px] items-center gap-6 px-4">
          <Link href="/" className="flex shrink-0 items-center gap-2 leading-none">
            <span className="text-[14px] font-semibold tracking-tight">StrawHat</span>
            <span className="hidden text-[12px] text-muted sm:inline">Finance Assistant</span>
          </Link>

          <nav className="flex items-center gap-0.5" aria-label="Primary">
            {NAV.map(({ href, label, Icon }) => {
              const active = pathname === href;
              return (
                <Link key={href} href={href}
                  aria-current={active ? 'page' : undefined}
                  className={`flex items-center gap-1.5 rounded-sm px-2.5 py-1.5 text-[13px] transition-colors
                    ${active ? 'bg-raised text-ink' : 'text-muted hover:text-ink'}`}>
                  <Icon size={15} weight={active ? 'fill' : 'regular'} aria-hidden />
                  {label}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto flex shrink-0 items-center gap-3">
            {meta}
            <ClearHistoryButton />
            <ThemeToggle />
          </div>
        </div>
      </header>
      {children}
    </div>
  );
}

function ClearHistoryButton() {
  const [state, setState] = useState<'idle' | 'busy' | 'done' | 'error'>('idle');
  const run = async () => {
    if (state === 'busy') return;
    if (!window.confirm('Clear all chat history and observability metrics?')) return;
    setState('busy');
    try {
      await clearHistory();
      setState('done');
    } catch {
      setState('error');
    }
    setTimeout(() => setState('idle'), 2000);
  };
  const label = state === 'busy' ? 'Clearing…' : state === 'done' ? 'Cleared' : state === 'error' ? 'Failed' : 'Clear History';
  return (
    <button type="button" onClick={run} disabled={state === 'busy'}
      title="Forget every conversation and reset the observability counters"
      className={`flex items-center gap-1.5 rounded-sm border border-line px-2.5 py-1.5 text-[13px] transition-colors
        ${state === 'error' ? 'text-warning' : 'text-muted hover:text-ink'} disabled:opacity-60`}>
      <Trash size={15} aria-hidden />
      {label}
    </button>
  );
}
