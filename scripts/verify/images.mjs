// G8: both application images build from a clean context.
import { run } from './_run.mjs';
import { pass, fail } from './_lib.mjs';

const r = run('docker', ['compose', 'build', 'api', 'web']);
if (r.status !== 0) fail('G8', `build failed:\n${r.out.slice(-2000)}`);

for (const [image, cmd] of [
  ['tbx-api:dev',  ['python', '-c', 'import app.main; print("api-import-ok")']],
  ['tbx-web:dev',  ['node', '-e', 'console.log("web-node-ok")']],
]) {
  const probe = run('docker', ['run', '--rm', '--entrypoint', cmd[0], image, ...cmd.slice(1)]);
  if (probe.status !== 0) fail('G8', `${image} not runnable:\n${probe.out.slice(-800)}`);
}

const prompts = run('docker', ['run', '--rm', '--entrypoint', 'python', 'tbx-api:dev',
  '-c', 'from app.agents.prompts import PROMPT_DIR, load; load("scope_and_plan_v1"); print("prompts-ok", PROMPT_DIR)']);
if (prompts.status !== 0) fail('G8', `prompts missing from image:\n${prompts.out.slice(-600)}`);

for (const image of ['tbx-api:dev', 'tbx-web:dev']) {
  const who = run('docker', ['run', '--rm', '--entrypoint', 'id', image, '-u']);
  if (who.out.trim() === '0') fail('G8', `${image} runs as root`);
}

pass('G8', 'tbx-api:dev and tbx-web:dev build, import and run',
     prompts.out.match(/prompts-ok.*/)?.[0] ?? '',
     'both images run as non-root');
