import { useEffect, useState } from 'react';
import { api, fmt, type AppRecord } from '../api';
import { useHover } from '../components/Tooltip';
import { EmptyState, ErrorBanner, Panel, SkeletonRows, StatusPill } from '../components/ui';
import { ClientSwitch } from './MockApi';

const COLUMNS = ['client_id', 'app_id', 'app_name', 'classification', 'risk_score', 'users', 'raw_notes', 'notes_truncated', 'times_collected', 'updated_at'];

export default function Database({ version }: { version: number }) {
  const hover = useHover();
  const [client, setClient] = useState('all');
  const [rows, setRows] = useState<AppRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRows(null);
    api.records(client === 'all' ? undefined : client)
      .then(r => { setRows(r); setError(null); })
      .catch(e => { setError((e as Error).message); setRows([]); });
  }, [client, version]);

  return (
    <>
      <div className="toolbar">
        <div>
          <h1>Step 3. The database</h1>
          <p className="muted">Table <code>app_usage_records</code>. One row per <code>(client_id, app_id)</code>, enforced by a UNIQUE constraint.</p>
        </div>
        <ClientSwitch value={client} onChange={setClient} options={['all', 'acme', 'vontier']} />
      </div>
      <ErrorBanner message={error} />

      <div className="grid">
        <Panel span={12} flush title={rows ? `${rows.length} rows` : 'Loading'}
               subtitle="Hover a row for details. A dash means NULL in the database.">
          <div className="table-scroll">
            <table className="table sticky compact">
              <thead><tr>{COLUMNS.map(c => <th key={c} className={['risk_score', 'users', 'times_collected'].includes(c) ? 'num' : ''}>{c}</th>)}</tr></thead>
              <tbody>
                {rows === null && <SkeletonRows cols={COLUMNS.length} />}
                {rows?.length === 0 && (
                  <tr><td colSpan={COLUMNS.length}><EmptyState title="No rows yet" body="Run a collection in step 2 to fill this table." /></td></tr>
                )}
                {rows?.map(r => (
                  <tr key={r.id} {...hover(
                    <div>
                      <div className="tt-title">{r.client_id} / {r.app_id}</div>
                      <div>classification: <b className={r.classification === 'unsanctioned' ? 'tt-red' : ''}>{r.classification}</b></div>
                      <div>risk_score: {r.risk_score ?? <b className="tt-red">NULL (API sent null)</b>}</div>
                      <div>raw_notes: {r.raw_notes?.length ?? 0} chars{r.notes_truncated ? ' (cut from 650)' : ''}</div>
                      <div>times_collected: {r.times_collected} (updated, not duplicated)</div>
                      <div>created_at: {fmt.date(r.created_at)}</div>
                    </div>,
                  )}>
                    <td className="mono">{r.client_id}</td>
                    <td className="mono">{r.app_id}</td>
                    <td>{r.app_name}</td>
                    <td><StatusPill status={r.classification} /></td>
                    <td className="num">{r.risk_score ?? <span className="red-text strong">—</span>}</td>
                    <td className="num">{fmt.num(r.users)}</td>
                    <td className="notes-cell"><span className="ellipsis">{r.raw_notes ?? '—'}</span></td>
                    <td>{r.notes_truncated ? <span className="red-text strong">true</span> : <span className="muted">false</span>}</td>
                    <td className="num">{r.times_collected}</td>
                    <td className="muted">{fmt.date(r.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </>
  );
}
