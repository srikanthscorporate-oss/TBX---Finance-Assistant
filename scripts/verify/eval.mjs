// G5: a golden set of >=50 questions exists and the runner measures accuracy
// against independently computed expectations, writing a categorised report.
import fs from 'node:fs';
import path from 'node:path';
import { run } from './_run.mjs';
import { ROOT, pass, fail } from './_lib.mjs';

const goldenPath = path.join(ROOT, 'evaluation/golden/questions.json');
if (!fs.existsSync(goldenPath)) fail('G5', 'golden set missing');
const golden = JSON.parse(fs.readFileSync(goldenPath, 'utf8'));

const turns = golden.length + golden.reduce((a, q) => a + (q.follow_ups?.length || 0), 0);
if (golden.length < 50) fail('G5', `only ${golden.length} golden questions (need >=50)`);

const cats = new Set(golden.map(q => q.category));
for (const required of ['exact', 'vendor', 'date', 'grouping', 'reconciliation',
                        'multi_turn', 'ambiguous', 'unsupported', 'missing_data',
                        'adversarial'])
  if (!cats.has(required)) fail('G5', `golden set missing category: ${required}`);

// Every question must declare an expectation; a question that cannot fail is
// not a test.
for (const q of golden) {
  if (!q.expected_state && !q.acceptable_states)
    fail('G5', `${q.id} declares no expected state`);
  if (q.expected_state === 'any' && !q.acceptable_states &&
      !q.must_not_contain && !q.must_not_hedge)
    fail('G5', `${q.id} has expected_state "any" with no other assertion`);
}

const r = run('python3', ['scripts/run_evaluation.py']);
if (r.status !== 0) fail('G5', `runner failed:\n${r.out.slice(-1200)}`);

const reportPath = path.join(ROOT, 'evaluation/results/latest.json');
if (!fs.existsSync(reportPath)) fail('G5', 'no report written');
const rep = JSON.parse(fs.readFileSync(reportPath, 'utf8'));

if (rep.turns !== turns) fail('G5', `report covers ${rep.turns} turns, golden set has ${turns}`);
if (rep.transport_errors) fail('G5', `${rep.transport_errors} turns failed to reach the API`);
for (const k of ['overall_accuracy', 'numeric_accuracy', 'grounding_rate',
                 'hallucination_free_rate', 'state_accuracy'])
  if (typeof rep[k] !== 'number') fail('G5', `report missing metric: ${k}`);
if (!rep.by_category || Object.keys(rep.by_category).length < 8)
  fail('G5', 'report lacks a per-category breakdown');
if (!rep.efficiency || typeof rep.efficiency.avg_tokens_per_turn !== 'number')
  fail('G5', 'report lacks efficiency metrics');
if (!rep.planner) fail('G5', 'report does not record which planner produced it');

// Guard the headline: grounding and hallucination are the scored properties.
if (rep.grounding_rate < 1) fail('G5', `grounding rate ${rep.grounding_rate} < 1.0`);
if (rep.hallucination_free_rate < 1)
  fail('G5', `hallucination-free rate ${rep.hallucination_free_rate} < 1.0`);

pass('G5', `${golden.length} questions / ${turns} turns across ${cats.size} categories`,
     `planner=${rep.planner} -- ${rep.caveat}`,
     `overall ${(rep.overall_accuracy * 100).toFixed(1)}%, numeric ${(rep.numeric_accuracy * 100).toFixed(1)}%`,
     `grounding ${(rep.grounding_rate * 100).toFixed(0)}%, hallucination-free ${(rep.hallucination_free_rate * 100).toFixed(0)}%`,
     `${rep.efficiency.avg_tokens_per_turn} tokens/turn, escalation ${(rep.efficiency.escalation_rate * 100).toFixed(1)}%`);
