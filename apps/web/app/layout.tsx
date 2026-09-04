import type { Metadata } from 'next';
import { GeistSans } from 'geist/font/sans';
import { GeistMono } from 'geist/font/mono';
import './globals.css';

export const metadata: Metadata = {
  title: 'StrawHat Finance Assistant',
  description:
    'Ask about spend, vendor payouts and reconciliation. Every figure is computed from your data and verified before it is shown.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <body className="min-h-[100dvh] font-sans antialiased">{children}</body>
    </html>
  );
}
