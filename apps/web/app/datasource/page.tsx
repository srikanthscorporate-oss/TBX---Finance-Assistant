import DataSource from '@/components/DataSource';
import Shell from '@/components/Shell';
import { getSourceStatusServer } from '@/lib/server-api';

export const metadata = {
  title: 'Data Source · StrawHat Finance Assistant',
  description: 'Connect a MySQL endpoint and make it the dataset the assistant answers from.',
};

export const dynamic = 'force-dynamic';

export default async function Page() {
  const status = await getSourceStatusServer();
  return (
    <Shell>
      <main className="mx-auto w-full max-w-[1400px] px-4 py-6">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div className="space-y-1">
            <h1 className="text-[20px] font-semibold tracking-tight">Data Source</h1>
            <p className="max-w-[70ch] text-[13px] leading-6 text-ink-2">
              Point the assistant at your own MySQL database. The endpoint is validated, its tables are
              shown here, and once initialized every answer in the chat is computed from that data
              through the same verified path.
            </p>
          </div>
        </div>
        <DataSource initialStatus={status} />
      </main>
    </Shell>
  );
}
