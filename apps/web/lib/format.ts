const SYMBOL: Record<string, string> = { INR: '₹', USD: '$', EUR: '€', GBP: '£', JPY: '¥' };

export function symbolFor(currency?: string | null): string {
  return SYMBOL[(currency ?? '').toUpperCase()] ?? '';
}

/** Axis-scale money. Indian units when the currency is INR, else SI. */
export function compactMoney(n: number, currency?: string | null): string {
  const s = symbolFor(currency);
  const abs = Math.abs(n);
  if ((currency ?? '').toUpperCase() === 'INR') {
    if (abs >= 1e7) return `${s}${(n / 1e7).toFixed(2)}Cr`;
    if (abs >= 1e5) return `${s}${(n / 1e5).toFixed(2)}L`;
  } else {
    if (abs >= 1e9) return `${s}${(n / 1e9).toFixed(2)}B`;
    if (abs >= 1e6) return `${s}${(n / 1e6).toFixed(2)}M`;
  }
  if (abs >= 1e3) return `${s}${(n / 1e3).toFixed(1)}k`;
  return `${s}${n.toFixed(0)}`;
}

export function fullMoney(n: number, currency?: string | null): string {
  return `${symbolFor(currency)}${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function compactNumber(n: number): string {
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return n.toLocaleString();
}

export function pct(n: number, digits = 1): string {
  return `${(n * 100).toFixed(digits)}%`;
}

export function ms(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(2)}s` : `${Math.round(n)}ms`;
}
