import { Fragment, useEffect, useMemo, useState } from 'react';
import { api, fmt, type AppRecord, type ClientSummary } from '../api';
import { useHover } from '../components/Tooltip';
import { EmptyState, ErrorBanner, Kpi, Panel } from '../components/ui';
import { ClientSwitch } from './MockApi';

export default function Analytics({ version, onRun }: { version: number; onRun: () => void }) {
  const hover = useHover();
  const [rows, setRows] = useState<AppRecord[] | null>(null);
  const [summary, setSummary] = useState<ClientSummary[]>([]);
  const [riskClient, setRiskClient] = useState('acme');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.records(), api.summary()])
      .then(([r, s]) => { setRows(r); setSummary(s.clients); setError(null); })
      .catch(e => setError((e as Error).message));
  }, [version]);

  const clients = useMemo(() => [...new Set((rows ?? []).map(r => r.client_id))], [rows]);
  const apps = useMemo(() => [...new Map((rows ?? []).map(r => [r.app_id, r.app_name])).entries()], [rows]);
  const get = (cid: string, appId: string) => rows?.find(r => r.client_id === cid && r.app_id === appId);

  const header = (
    <div className="toolbar">
      <div>
        <h1>Step 4. Analytics</h1>
        <p className="muted">Built from the rows in the database. Hover anything for details.</p>
      </div>
    </div>
  );

  if (error) return <>{header}<ErrorBanner message={error} /></>;
  if (rows && rows.length === 0) {
    return (
      <>{header}
        <div className="grid"><Panel span={12}>
          <EmptyState title="No data yet" body="Run a collection first." action={<button className="btn btn-primary" onClick={onRun}>Run collection</button>} />
        </Panel></div>
      </>
    );
  }

  const total = rows?.length ?? 0;
  const sanctioned = rows?.filter(r => r.classification === 'sanctioned') ?? [];
  const unsanctioned = rows?.filter(r => r.classification === 'unsanctioned') ?? [];
  const noRisk = rows?.filter(r => r.risk_score === null) ?? [];
  const names = (list: AppRecord[]) => list.map(r => `${r.client_id}: ${r.app_name}`);

  const maxUsers = Math.max(1, ...(rows ?? []).map(r => r.users ?? 0));
  const riskRows = (rows ?? []).filter(r => r.client_id === riskClient);

  return (
    <>
      {header}
      <div className="grid">
        <div className="kpi-row four span-12">
          <div {...hover(<HoverList title="Rows in app_usage_records" items={[`${clients.length} clients × ${apps.length} apps`]} />)}>
            <Kpi label="Apps collected" value={fmt.num(total)} note={`${clients.length} clients`} />
          </div>
          <div {...hover(<HoverList title="Sanctioned (on the client's list)" items={names(sanctioned)} />)}>
            <Kpi label="Sanctioned" value={fmt.num(sanctioned.length)} note="allowed by the client" />
          </div>
          <div {...hover(<HoverList title="Unsanctioned (not on the list)" items={names(unsanctioned)} red />)}>
            <Kpi label="Unsanctioned" value={fmt.num(unsanctioned.length)} tone="red" note="not on the client's list" />
          </div>
          <div {...hover(<HoverList title="risk_score was null in the API" items={[...names(noRisk), 'Stored as NULL, not 0: unknown is not safe.']} />)}>
            <Kpi label="Missing risk score" value={fmt.num(noRisk.length)} note="stored as NULL" />
          </div>
        </div>

        <Panel span={12} title="Which apps each client allows"
               subtitle="Same 6 apps, different answer per client. Black = sanctioned, red = unsanctioned.">
          <div className="matrix" style={{ gridTemplateColumns: `100px repeat(${apps.length}, minmax(0, 1fr))` }}>
            <div />
            {apps.map(([id, name]) => <div key={id} className="matrix-head">{name}</div>)}
            {clients.map(cid => (
              <Fragment key={cid}>
                <div className="matrix-label mono">{cid}</div>
                {apps.map(([id]) => {
                  const r = get(cid, id);
                  if (!r) return <div key={`${cid}-${id}`} className="cell cell-empty">—</div>;
                  return (
                    <div key={`${cid}-${id}`} className={`cell ${r.classification === 'sanctioned' ? 'cell-ok' : 'cell-bad'}`}
                         {...hover(<RecordTip r={r} />)}>
                      {r.classification}
                    </div>
                  );
                })}
              </Fragment>
            ))}
          </div>
        </Panel>

        <Panel span={6} title="Risk score by app" subtitle="0 to 100. Dashed bar = no score (NULL)."
               actions={<ClientSwitch value={riskClient} onChange={setRiskClient} options={clients} />}>
          <div className="vchart">
            {riskRows.map(r => (
              <div key={r.app_id} className="vcol" {...hover(<RecordTip r={r} />)}>
                <div className="vval">{r.risk_score ?? 'NULL'}</div>
                <div className="vtrack">
                  {r.risk_score === null
                    ? <div className="vbar vbar-null" style={{ height: '100%' }} />
                    : <div className={`vbar ${r.classification === 'sanctioned' ? 'vbar-ink' : 'vbar-red'}`} style={{ height: `${Math.max(2, r.risk_score)}%` }} />}
                </div>
                <div className="vlabel">{r.app_name}</div>
              </div>
            ))}
          </div>
          <div className="legend">
            <span><i className="swatch seg-0" />sanctioned</span>
            <span><i className="swatch seg-red" />unsanctioned</span>
            <span><i className="swatch swatch-null" />no score</span>
          </div>
        </Panel>

        <Panel span={6} title="Active users by app" subtitle="Each client reports its own numbers.">
          <div className="hchart">
            {apps.map(([id, name]) => (
              <div key={id} className="hrow">
                <div className="hlabel">{name}</div>
                <div className="hbars">
                  {clients.map((cid, i) => {
                    const r = get(cid, id);
                    const users = r?.users ?? 0;
                    return (
                      <div key={cid} className="hbar-line" {...(r ? hover(<RecordTip r={r} />) : {})}>
                        <div className={`hbar seg-${i % 2}`} style={{ width: `${(users / maxUsers) * 100}%` }} />
                        <span className="hval">{users}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
          <div className="legend">
            {clients.map((cid, i) => <span key={cid}><i className={`swatch seg-${i % 2}`} />{cid}</span>)}
          </div>
        </Panel>

        <Panel span={12} flush title="Summary per client" subtitle="Calculated in SQL with one GROUP BY client_id query">
          <table className="table">
            <thead>
              <tr>
                <th>client_id</th><th className="num">apps</th><th className="num">sanctioned</th><th className="num">unsanctioned</th>
                <th className="num">avg risk_score</th><th className="num">missing risk_score</th><th className="num">notes truncated</th><th className="num">total users</th>
              </tr>
            </thead>
            <tbody>
              {summary.map(s => (
                <tr key={s.client_id}>
                  <td className="mono strong">{s.client_id}</td>
                  <td className="num">{s.apps}</td>
                  <td className="num">{s.sanctioned}</td>
                  <td className="num red-text">{s.unsanctioned}</td>
                  <td className="num" {...hover('AVG() skips NULL, so the missing score does not pull the average down to 0.')}>{s.avg_risk ?? '—'}</td>
                  <td className="num">{s.missing_risk}</td>
                  <td className="num">{s.truncated}</td>
                  <td className="num">{fmt.num(s.users)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
    </>
  );
}

function RecordTip({ r }: { r: AppRecord }) {
  return (
    <div>
      <div className="tt-title">{r.app_name} <span className="tt-dim">({r.client_id})</span></div>
      <div>classification: <b className={r.classification === 'unsanctioned' ? 'tt-red' : ''}>{r.classification}</b></div>
      <div>risk_score: {r.risk_score ?? <b className="tt-red">NULL</b>}</div>
      <div>users: {fmt.num(r.users)}</div>
      {r.notes_truncated && <div className="tt-red">raw_notes cut to 500 chars</div>}
    </div>
  );
}

function HoverList({ title, items, red }: { title: string; items: string[]; red?: boolean }) {
  return (
    <div>
      <div className="tt-title">{title}</div>
      {items.map(i => <div key={i} className={red ? 'tt-red' : ''}>{i}</div>)}
    </div>
  );
}
