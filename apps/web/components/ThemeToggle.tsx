'use client';

import { useEffect, useState } from 'react';
import { Moon, Sun } from '@phosphor-icons/react';

type Mode = 'light' | 'dark';

export default function ThemeToggle() {
  const [mode, setMode] = useState<Mode | null>(null);

  useEffect(() => {
    const stored = (() => {
      try { return localStorage.getItem('tbx-theme') as Mode | null; } catch { return null; }
    })();
    const initial: Mode = stored
      ?? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    setMode(initial);
    document.documentElement.dataset.theme = initial;
  }, []);

  const toggle = () => {
    const next: Mode = mode === 'dark' ? 'light' : 'dark';
    setMode(next);
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('tbx-theme', next); } catch { /* private mode */ }
  };

  return (
    <button
      onClick={toggle}
      aria-label={mode === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
      className="grid h-8 w-8 place-items-center rounded-sm text-muted transition-colors
                 hover:bg-raised hover:text-ink"
    >
      {/* Empty until mounted so server and client markup agree. */}
      {mode === 'dark' ? <Sun size={16} weight="bold" />
        : mode === 'light' ? <Moon size={16} weight="bold" /> : <span className="h-4 w-4" />}
    </button>
  );
}
