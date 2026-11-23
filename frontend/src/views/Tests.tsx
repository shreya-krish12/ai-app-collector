import { useEffect, useMemo, useState } from 'react';
import { api, fmt, type TestCase, type TestResult } from '../api';
import { Bar, EmptyState, ErrorBanner, Kpi, Panel, SkeletonRows, StatusPill } from '../components/ui';

const MODULE_LABEL: Record<string, string> = {
  test_pagination: 'Pagination',
  test_retry: '429 retries and backoff',
  test_normalization: 'Normalisation (truncation, null risk_score)',
  test_idempotency: 'Idempotent persistence',
  test_multi_tenant: 'Multi-tenant isolation (acme vs vontier)',
  test_modes: 'Mock vs real-time mode',
  test_api: 'HTTP API',
  test_config_rules: 'Configuration (editable rules)',
  test_edge_cases: 'Edge cases (N pages, repeated 429, unknown apps, emojis, re-run)',
};

export default function Tests() {
  const [result, setResult] = useState<TestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.lastTests().then(setResult).catch(() => undefined); }, []);

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      setResult(await api.runTests());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const groups = useMemo(() => {
    const map = new Map<string, TestCase[]>();
    for (const t of result?.tests ?? []) {
      map.set(t.module, [...(map.get(t.module) ?? []), t]);
    }
    return [...map.entries()];
  }, [result]);

  const c = result?.counts;

  return (
    <>
      <div className="toolbar">
        <div>
          <h1>Step 5. Tests</h1>
          <p className="muted">Runs the real pytest suite. Each group matches a requirement from the assignment.</p>
        </div>
        <button className="btn btn-primary" onClick={run} disabled={running}>
          {running ? 'Running pytest…' : 'Run test suite'}
        </button>
      </div>
      <ErrorBanner message={error ?? result?.error ?? null} />

      {!result && !running ? (
        <div className="grid">
          <Panel span={12}>
            <EmptyState title="No test results yet" body="Run the suite to see every test case and line coverage per module."
                        action={<button className="btn btn-primary" onClick={run}>Run test suite</button>} />
          </Panel>
        </div>
      ) : (
        <div className={running ? 'grid is-loading' : 'grid'}>
          <div className="kpi-row span-12">
            <Kpi label="Result" value={result ? <StatusPill status={result.status} /> : '—'} note={result ? fmt.date(result.started_at) : undefined} />
            <Kpi label="Passed" value={fmt.num(c?.passed)} note={c ? `of ${c.total} tests` : undefined} />
            <Kpi label="Failed" value={fmt.num(c ? c.failed + c.error : undefined)} tone={c && c.failed + c.error > 0 ? 'red' : 'ink'} />
            <Kpi label="Line coverage" value={result?.coverage ? `${result.coverage.percent}%` : '—'} note="app_collector package" />
            <Kpi label="Duration" value={result?.duration !== undefined ? `${result.duration} s` : '—'} note="Including coverage" />
          </div>

          <Panel span={7} title="Test cases" subtitle="Grouped by requirement" flush>
            <div className="table-scroll">
              <table className="table sticky">
                <thead>
                  <tr>
                    <th>Test</th>
                    <th>Status</th>
                    <th className="num">Time (s)</th>
                  </tr>
                </thead>
                <tbody>
                  {running && !result && <SkeletonRows cols={3} rows={10} />}
                  {groups.map(([module, tests]) => {
                    const passed = tests.filter(t => t.status === 'passed').length;
                    return (
                      <Group key={module} title={MODULE_LABEL[module] ?? module} module={module}
                             passed={passed} total={tests.length} tests={tests} />
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel span={5} title="Coverage by file" flush>
            <div className="table-scroll">
              <table className="table sticky">
                <thead>
                  <tr>
                    <th>File</th>
                    <th className="num">Stmts</th>
                    <th className="num">Miss</th>
                    <th style={{ width: 120 }}>Covered</th>
                  </tr>
                </thead>
                <tbody>
                  {result?.coverage?.files.filter(f => f.statements > 0).map(f => (
                    <tr key={f.file}>
                      <td className="mono small">{f.file.replace('app_collector/', '')}</td>
                      <td className="num">{f.statements}</td>
                      <td className="num">{f.missing}</td>
                      <td>
                        <div className="cov-cell">
                          <Bar value={f.percent} max={100} tone={f.percent < 70 ? 'red' : 'ink'} />
                          <span className="num small">{f.percent}%</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
                {result?.coverage && (
                  <tfoot>
                    <tr><td>Total</td><td /><td /><td className="num">{result.coverage.percent}%</td></tr>
                  </tfoot>
                )}
              </table>
            </div>
          </Panel>

          {result?.output_tail && result.status !== 'passed' && (
            <Panel span={12} title="pytest output (last lines)">
              <pre className="log pre">{result.output_tail}</pre>
            </Panel>
          )}
        </div>
      )}
    </>
  );
}

function Group({ title, module, passed, total, tests }: {
  title: string; module: string; passed: number; total: number; tests: TestCase[];
}) {
  return (
    <>
      <tr className="group-row">
        <td>{title} <span className="mono-sub inline">{module}.py</span></td>
        <td>{passed === total ? 'All passed' : <span className="red-text">{total - passed} failing</span>}</td>
        <td className="num">{passed}/{total}</td>
      </tr>
      {tests.map(t => (
        <tr key={t.classname + t.name}>
          <td className="indent">
            <span className="mono small">{t.name}</span>
            {t.message && <div className="red-text small">{t.message}</div>}
          </td>
          <td><StatusPill status={t.status} /></td>
          <td className="num">{t.duration.toFixed(3)}</td>
        </tr>
      ))}
    </>
  );
}
