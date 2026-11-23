import { useCallback, useEffect, useRef, useState } from 'react';
import { api, fmt, type Config, type Mode, type Run } from './api';
import { TooltipProvider } from './components/Tooltip';
import { ErrorBanner, StatusPill } from './components/ui';
import MockApi from './views/MockApi';
import Live from './views/Live';
import Database from './views/Database';
import Analytics from './views/Analytics';
import Tests from './views/Tests';
import Configuration from './views/Configuration';
import './styles.css';

type Tab = 'mock' | 'live' | 'db' | 'analytics' | 'tests' | 'config';

const TABS: { id: Tab; label: string }[] = [
  { id: 'mock', label: 'Mock API' },
  { id: 'live', label: 'Live collection' },
  { id: 'db', label: 'Database' },
  { id: 'analytics', label: 'Analytics' },
  { id: 'tests', label: 'Tests' },
  { id: 'config', label: 'Configuration' },
];

export default function App() {
  const [tab, setTab] = useState<Tab>('mock');
  const [mode, setMode] = useState<Mode>('mock');
  const [config, setConfig] = useState<Config | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [dataVersion, setDataVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const pollRef = useRef<number | undefined>(undefined);
  const running = run?.status === 'running';

  // Connect, and keep retrying every 3 s while the API server is down.
  useEffect(() => {
    if (online) return;
    let cancelled = false;
    let timer: number | undefined;
    const connect = async () => {
      try {
        const cfg = await api.config();
        if (cancelled) return;
        setConfig(cfg);
        setMode(cfg.default_mode);
        setOnline(true);
        setError(null);
        setDataVersion(v => v + 1);
        const [latest] = await api.runs(1);
        if (latest && !cancelled) setRun(await api.run(latest.id));
      } catch {
        if (cancelled) return;
        setOnline(false);
        setError('Cannot reach the API server. Start it with "python api_server.py". This page reconnects by itself.');
        timer = window.setTimeout(connect, 3000);
      }
    };
    connect();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [online]);

  const poll = useCallback((id: string) => {
    window.clearTimeout(pollRef.current);
    const tick = async (after: number) => {
      try {
        const update = await api.run(id, after);
        let last = after;
        setRun(prev => {
          const events = [...(prev?.id === id ? prev.events ?? [] : []), ...(update.events ?? [])];
          last = events.length ? events[events.length - 1].seq : after;
          return { ...update, events };
        });
        if (update.status === 'running') pollRef.current = window.setTimeout(() => tick(last), 300);
        else setDataVersion(v => v + 1);
      } catch (e) {
        setError((e as Error).message);
      }
    };
    tick(0);
  }, []);
  useEffect(() => () => window.clearTimeout(pollRef.current), []);

  const startRun = async () => {
    setError(null);
    try {
      const created = await api.startRun(mode);
      setRun({ ...created, events: [] });
      setTab('live');
      poll(created.id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <TooltipProvider>
      <div className="app">
        <header className="topbar">
          <div className="brand">
            <div className="brand-mark" aria-hidden />
            <div>
              <div className="brand-title">AI App Collector</div>
              <div className="brand-sub">Clients: acme, vontier</div>
            </div>
          </div>
          <div className="topbar-controls">
            <span className="topbar-label">Mode</span>
            <div className="segmented" role="tablist" aria-label="Collection mode">
              {(['mock', 'real'] as Mode[]).map(m => (
                <button key={m} role="tab" aria-selected={mode === m} className={mode === m ? 'active' : ''}
                        onClick={() => setMode(m)} disabled={running}>
                  {fmt.mode(m)}
                </button>
              ))}
            </div>
            <button className="btn btn-primary" onClick={startRun} disabled={running || !online}>
              {running ? 'Collecting…' : 'Run collector'}
            </button>
          </div>
        </header>

        <nav className="tabbar">
          <div className="tabs">
            {TABS.map(t => (
              <button key={t.id} className={tab === t.id ? 'tab active' : 'tab'} onClick={() => setTab(t.id)}>
                {t.label}
              </button>
            ))}
          </div>
          <div className="tabbar-status">
            <span className={`dot ${online ? 'dot-ok' : 'dot-bad'}`} />
            <span className="muted">{online === null ? 'Connecting' : online ? 'API connected' : 'API offline'}</span>
            {run && (<><span className="sep" /><span className="muted">Last run: {fmt.mode(run.mode)}</span><StatusPill status={run.status} /></>)}
          </div>
        </nav>

        <main className="content">
          <ErrorBanner message={error} />
          {tab === 'mock' && <MockApi onNext={() => setTab('live')} />}
          {tab === 'live' && <Live run={run} mode={mode} upstreamUrl={config?.upstream_base_url ?? ''} onRun={startRun} onNext={() => setTab('db')} />}
          {tab === 'db' && <Database version={dataVersion} />}
          {tab === 'analytics' && <Analytics version={dataVersion} onRun={startRun} />}
          {tab === 'tests' && <Tests />}
          {tab === 'config' && <Configuration />}
        </main>
      </div>
    </TooltipProvider>
  );
}
