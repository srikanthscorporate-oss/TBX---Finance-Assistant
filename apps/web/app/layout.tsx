import type { Metadata } from 'next';
import { GeistSans } from 'geist/font/sans';
import { GeistMono } from 'geist/font/mono';
import './globals.css';

export const metadata: Metadata = {
  title: 'StrawHat Finance Assistant',
  description:
    'Ask about your bank transactions, counterparties, accounts and balances. Every figure is computed from your statement data and verified before it is shown.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <body className="min-h-[100dvh] font-sans antialiased">{children}</body>
    </html>
  );
}
