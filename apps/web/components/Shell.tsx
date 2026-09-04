'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ChartLineUp, ChatCircleDots } from '@phosphor-icons/react';
import ThemeToggle from './ThemeToggle';

const NAV = [
  { href: '/', label: 'Ask', Icon: ChatCircleDots },
  { href: '/observability', label: 'Observability', Icon: ChartLineUp },
];

export default function Shell({ children, meta }: {
  children: React.ReactNode; meta?: React.ReactNode;
}) {
  const pathname = usePathname();
  return (
    <div className="min-h-[100dvh]">
      <header className="sticky top-0 z-20 border-b border-line bg-bg/85 backdrop-blur">
        <div className="mx-auto flex h-[60px] max-w-6xl items-center gap-4 px-4">
          <Link href="/" className="flex items-baseline gap-2">
            <span className="text-[14px] font-semibold tracking-tight">StrawHat</span>
            <span className="hidden text-[12px] text-muted sm:inline">Finance Assistant</span>
          </Link>

          <nav className="ml-2 flex items-center gap-0.5">
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

          <div className="ml-auto flex items-center gap-3">
            {meta}
            <ThemeToggle />
          </div>
        </div>
      </header>
      {children}
    </div>
  );
}
