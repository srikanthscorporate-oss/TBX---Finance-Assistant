import Observability from '@/components/Observability';
import Shell from '@/components/Shell';
import { getEvaluationsServer, getJudgeServer, getUsageServer } from '@/lib/server-api';

export const metadata = {
  title: 'Observability · StrawHat Finance Assistant',
  description: 'Token spend, latency, model mix and evaluation accuracy for the assistant.',
};

// Always render fresh: these are live operational counters.
export const dynamic = 'force-dynamic';

export default async function Page() {
  const [usage, evals, judge] = await Promise.all([getUsageServer(), getEvaluationsServer(), getJudgeServer()]);
  return (
    <Shell>
      <main className="mx-auto w-full max-w-6xl px-4 py-6">
        <div className="mb-5 space-y-1.5">
          <h1 className="text-[20px] font-semibold tracking-tight">Observability</h1>
          <p className="max-w-[70ch] text-[13px] leading-6 text-ink-2">
            What the assistant costs and how well it performs. These are operational
            counters about the model, not your financial records.
          </p>
        </div>
        <Observability initialUsage={usage} initialEvals={evals} initialJudge={judge} />
      </main>
    </Shell>
  );
}
