import { useEffect, useState } from 'react';
import { api, fmt, type MockData, type MockItem } from '../api';
import { useHover } from '../components/Tooltip';
import { ErrorBanner, Panel } from '../components/ui';

export default function MockApi({ onNext }: { onNext: () => void }) {
  const [data, setData] = useState<MockData | null>(null);
  const [client, setClient] = useState('acme');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.mockData().then(setData).catch(e => setError((e as Error).message)); }, []);

  const current = data?.clients.find(c => c.client_id === client);

  return (
    <>
      <div className="toolbar">
        <div>
          <p className="muted">This is the fake API the collector reads from. It returns 2 pages of apps for each client.</p>
        </div>
        <button className="btn btn-secondary" onClick={onNext}>Next: run the collector</button>
      </div>
      <ErrorBanner message={error} />

      <div className="grid">
        <Panel span={12} title="Response data"
               actions={<ClientSwitch value={client} onChange={setClient} options={data?.clients.map(c => c.client_id) ?? []} />}>
          {current && (
            <>
              <div className="sanctioned-line">
                <span className="label-inline">sanctioned_apps for <b>{client}</b>:</span>
                {current.sanctioned_apps.map(a => <span key={a} className="chip">{a}</span>)}
                <span className="muted small">Every other app is unsanctioned for {client}.</span>
              </div>
              <div className="two-col">
                <PageTable title="Page 1" request={`GET /apps?client_id=${client}`}
                           items={current.page_1.items} cursor={current.page_1.next_cursor} sanctioned={current.sanctioned_apps} />
                <PageTable title="Page 2" request={`GET /apps?client_id=${client}&cursor=page-2`} note="429 on first try"
                           items={current.page_2.items} cursor={current.page_2.next_cursor} sanctioned={current.sanctioned_apps} />
              </div>
            </>
          )}
        </Panel>

      </div>
    </>
  );
}

export function ClientSwitch({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <div className="switch">
      {options.map(o => (
        <button key={o} className={value === o ? 'active' : ''} onClick={() => onChange(o)}>{o}</button>
      ))}
    </div>
  );
}

function PageTable({ title, request, note, items, cursor, sanctioned }: {
  title: string; request: string; note?: string; items: MockItem[]; cursor: string | null; sanctioned: string[];
}) {
  const hover = useHover();
  const isSanctioned = (name: string) => sanctioned.some(s => s.toLowerCase() === name.toLowerCase());
  return (
    <div className="page-box">
      <div className="page-head">
        <span className="strong">{title}</span>
        <code className="req">{request}</code>
        {note && <span className="tag">{note}</span>}
      </div>
      <table className="table compact">
        <thead>
          <tr><th>app_id</th><th>app_name</th><th className="num">users</th><th className="num">risk_score</th><th className="num">raw_notes</th></tr>
        </thead>
        <tbody>
          {items.map(i => (
            <tr key={i.app_id} className={i.raw_notes.length > 500 || i.risk_score === null ? 'flag-row' : ''}
                {...hover(
                  <div>
                    <div className="tt-title">{i.app_name}</div>
                    <div>Will be stored as <b className={isSanctioned(i.app_name) ? '' : 'tt-red'}>{isSanctioned(i.app_name) ? 'sanctioned' : 'unsanctioned'}</b></div>
                    <div>risk_score: {i.risk_score === null ? <b className="tt-red">null → stored as NULL</b> : i.risk_score}</div>
                    <div>raw_notes: {i.raw_notes.length} chars{i.raw_notes.length > 500 ? <b className="tt-red"> → cut to 500</b> : ''}</div>
                    <div className="tt-quote">"{i.raw_notes.slice(0, 120).replace(/[\x00-\x1f]/g, '·')}{i.raw_notes.length > 120 ? '…' : ''}"</div>
                  </div>,
                )}>
              <td className="mono">{i.app_id}</td>
              <td>{i.app_name}</td>
              <td className="num">{fmt.num(i.users)}</td>
              <td className="num">{i.risk_score === null ? <span className="red-text strong">null</span> : i.risk_score}</td>
              <td className="num">{i.raw_notes.length > 500 ? <span className="red-text strong">{i.raw_notes.length} chars</span> : `${i.raw_notes.length} chars`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="page-foot mono">next_cursor: {cursor === null ? 'null' : `"${cursor}"`}</div>
    </div>
  );
}
