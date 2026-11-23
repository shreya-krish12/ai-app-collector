import { useEffect, useRef } from 'react';
import { fmt, type Mode, type Run, type RunEvent } from '../api';
import { useHover } from '../components/Tooltip';
import { EmptyState, Kpi, Panel, StatusPill } from '../components/ui';

export default function Live({ run, mode, upstreamUrl, onRun, onNext }: {
  run: Run | null; mode: Mode; upstreamUrl: string; onRun: () => void; onNext: () => void;
}) {
  const hover = useHover();
  const running = run?.status === 'running';
  const t = run?.summary?.totals;
  const clients = Object.keys(run?.summary?.clients ?? {});
  const events = run?.events ?? [];

  return (
    <>
      <div className="toolbar">
        <div>
          <h1>Step 2. Live collection</h1>
          <p className="muted">
            {mode === 'mock'
              ? 'Mock mode: the collector talks to the mock API inside Python (httpx.MockTransport). No network.'
              : `Real-time mode: the collector sends real HTTP requests to ${upstreamUrl}.`}
          </p>
        </div>
        <div className="toolbar-controls">
          <button className="btn btn-primary" onClick={onRun} disabled={running}>
            {running ? 'Collecting…' : `Run ${fmt.mode(mode).toLowerCase()} collection`}
          </button>
          <button className="btn btn-secondary" onClick={onNext} disabled={!run || running}>Next: see the database</button>
        </div>
      </div>

      {!run ? (
        <div className="grid">
          <Panel span={12}>
            <EmptyState title="Nothing collected yet"
                        body="Press the button to fetch both clients. You will see every request, the 429 retry, and what was saved."
                        action={<button className="btn btn-primary" onClick={onRun}>Run {fmt.mode(mode).toLowerCase()} collection</button>} />
          </Panel>
        </div>
      ) : (
        <div className="grid">
          <div className="kpi-row span-12">
            <Kpi label="Run" value={<StatusPill status={run.status} />} note={`${fmt.mode(run.mode)} · ${fmt.seconds(run.started_at, run.finished_at)}`} />
            <div {...hover('Records received from the API across both pages.')}><Kpi label="Received" value={fmt.num(t?.received)} note="from the API" /></div>
            <div {...hover('Rows that did not exist yet for this (client_id, app_id).')}><Kpi label="New rows" value={fmt.num(t?.inserted)} note="inserted" /></div>
            <div {...hover('Rows that already existed and were updated in place. Run twice to see this go up.')}><Kpi label="Updated rows" value={fmt.num(t?.updated)} note="no duplicates" /></div>
            <div {...hover('How many times a 429 forced the collector to wait and retry.')}><Kpi label="429 retries" value={fmt.num(t?.retries)} tone={t?.retries ? 'red' : 'ink'} note="waited, then retried" /></div>
          </div>

          {clients.map(cid => (
            <ClientLane key={cid} clientId={cid} run={run} events={events.filter(e => e.client_id === cid)} />
          ))}

          {events.length === 0 && !running && (
            <Panel span={12}>
              <p className="muted">This run's step-by-step log was cleared when the API server restarted. Run again to watch it live.</p>
            </Panel>
          )}
        </div>
      )}
    </>
  );
}

function ClientLane({ clientId, run, events }: { clientId: string; run: Run; events: RunEvent[] }) {
  const stats = run.summary?.clients[clientId];
  const listRef = useRef<HTMLOListElement>(null);
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight }); }, [events.length]);

  return (
    <Panel span={6} title={`client_id = "${clientId}"`}
           subtitle={stats ? `${stats.received} received · ${stats.inserted} new · ${stats.updated} updated · ${stats.sanctioned} sanctioned · ${stats.unsanctioned} unsanctioned` : undefined}
           actions={stats && <StatusPill status={stats.status} />}>
      <ol className="steps" ref={listRef}>
        {events.map(e => (
          <li key={e.seq} className={`step step-${kind(e)}`}>
            <span className="step-dot" />
            <span className="step-time mono">{fmt.time(e.ts)}</span>
            <span className="step-text">{e.message}</span>
          </li>
        ))}
        {run.status === 'running' && stats?.status !== 'completed' && (
          <li className="step step-wait"><span className="step-dot" /><span className="step-time" /><span className="step-text muted">working…</span></li>
        )}
      </ol>
      {stats?.error && <div className="banner-error">{stats.error}</div>}
    </Panel>
  );
}

function kind(e: RunEvent) {
  if (e.level !== 'info') return 'red';
  if (e.message.startsWith('Page') && e.message.includes('saved')) return 'saved';
  if (e.message.includes('raw_notes') || e.message.includes('risk_score')) return 'fix';
  return 'info';
}
