import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

interface Performance { n_days: number; total_return: number; cagr: number; sharpe: number; mdd: number }
interface Fold { fold: number; train_end: string; test_start: string; test_end: string; policy: string; oos_strategy: Performance }
interface Bootstrap { repetitions: number; ci95_monthly_excess: [number, number]; fraction_mean_above_zero: number }
interface Report {
  protocol: { policy: string; round_trip_cost_bps: number; one_way_cost_bps: number; sleeve_weights: Record<string, number> };
  folds: Fold[];
  stitched_strategy: Performance;
  statistics: { n_months: number; mean_monthly_excess: number; t_stat: number; p_value_two_sided: number; significant_at_5pct: boolean; iid: Bootstrap; block4: Bootstrap & { block_months: number } };
}
interface Daily { date: string; strategy: number; benchmark: number; fold: number }
const root = resolve(import.meta.dirname, '..');
const result = resolve(root, 'results/fixed_strategy_validation');
const report = JSON.parse(readFileSync(resolve(result, 'metrics.json'), 'utf8')) as Report;
assert.equal(report.protocol.policy, 'Robust_L60_M63_LV20');
assert.deepEqual(report.protocol.sleeve_weights, { leader: .6, mom63: .2, lowvol: .2 });
assert.equal(report.protocol.round_trip_cost_bps, 10);
assert.equal(report.protocol.one_way_cost_bps, 5);
assert.equal(report.folds.length, 5);
for (const [index, fold] of report.folds.entries()) {
  assert.equal(fold.fold, index+1);
  assert.ok(fold.train_end < fold.test_start);
  if (index > 0) assert.ok(report.folds[index-1].test_end < fold.test_start);
}
const lines = readFileSync(resolve(result, 'oos_returns.csv'), 'utf8').trim().split(/\r?\n/);
const header = lines.shift()!.split(',');
const daily: Daily[] = lines.map(line => {
  const fields = line.split(',');
  return { date: fields[header.indexOf('date')], strategy: Number(fields[header.indexOf('return_')]),
    benchmark: Number(fields[header.indexOf('benchmark')]), fold: Number(fields[header.indexOf('fold')]) };
});
assert.equal(new Set(daily.map(row => row.date)).size, daily.length);
assert.equal(daily.length, report.stitched_strategy.n_days);
let wealth = 1;
const months = new Map<string, { strategy: number; benchmark: number }>();
for (const row of daily) {
  const fold = report.folds[row.fold-1];
  assert.ok(row.date >= fold.test_start && row.date <= fold.test_end);
  assert.ok(Number.isFinite(row.strategy) && row.strategy > -1);
  wealth *= 1+row.strategy;
  const key = row.date.slice(0, 7);
  const month = months.get(key) ?? { strategy: 1, benchmark: 1 };
  month.strategy *= 1+row.strategy;
  month.benchmark *= 1+row.benchmark;
  months.set(key, month);
}
assert.ok(Math.abs(wealth-1-report.stitched_strategy.total_return) < 1e-8);
const excess = [...months.values()].map(month => month.strategy-month.benchmark);
const mean = excess.reduce((a,b) => a+b, 0)/excess.length;
const variance = excess.reduce((a,b) => a+(b-mean)**2, 0)/(excess.length-1);
assert.equal(excess.length, report.statistics.n_months);
assert.equal(excess.length, 30);
assert.ok(Math.abs(mean-report.statistics.mean_monthly_excess) < 1e-10);
assert.ok(Math.abs(mean/Math.sqrt(variance/excess.length)-report.statistics.t_stat) < 1e-10);
assert.equal(report.statistics.significant_at_5pct, report.statistics.p_value_two_sided < .05);
assert.equal(report.statistics.block4.block_months, 4);
for (const bootstrap of [report.statistics.iid, report.statistics.block4]) {
  assert.equal(bootstrap.repetitions, 10000);
  assert.ok(bootstrap.ci95_monthly_excess[0] <= bootstrap.ci95_monthly_excess[1]);
  assert.ok(bootstrap.fraction_mean_above_zero >= 0 && bootstrap.fraction_mean_above_zero <= 1);
}
const tests = spawnSync(process.env.VALIDATION_PYTHON ?? 'python',
  ['-m', 'pytest', 'tests/', '-q', '--disable-warnings', '--tb=short'],
  { cwd: root, encoding: 'utf8' });
process.stdout.write(tests.stdout);
process.stderr.write(tests.stderr);
assert.equal(tests.status, 0, tests.error?.message ?? 'Python validation tests failed');
console.log(`Verified archived ${daily.length} OOS sessions, ${months.size} months, five folds and statistical results; current safety and WFA regressions passed.`);
