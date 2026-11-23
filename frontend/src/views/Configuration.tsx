import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, type MissingRisk, type MockItem, type Rules, type RulesView } from '../api';
import { useHover } from '../components/Tooltip';
import { ErrorBanner, Panel, StatusPill } from '../components/ui';

/** Same matching rule as the backend: ignore case and extra spaces. */
const key = (name: string) => name.toLowerCase().split(/\s+/).filter(Boolean).join(' ');
const clean = (name: string) => name.split(/\s+/).filter(Boolean).join(' ');

export default function Configuration() {
  const [view, setView] = useState<RulesView | null>(null);
  const [draft, setDraft] = useState<Rules | null>(null);
  const [lengthText, setLengthText] = useState('');
  const [apps, setApps] = useState<MockItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = (v: RulesView) => {
    setView(v);
    setDraft(v.rules);
    setLengthText(String(v.rules.max_notes_length));
  };

  useEffect(() => {
    api.rules().then(load).catch(e => setError((e as Error).message));
    api.mockData()
      .then(d => setApps([...(d.clients[0]?.page_1.items ?? []), ...(d.clients[0]?.page_2.items ?? [])]))
      .catch(() => undefined);
  }, []);

  const limit = view?.max_notes_limit ?? 500;
  const lengthNum = Number(lengthText);
  const lengthError = !/^\d+$/.test(lengthText) || lengthNum < 1 || lengthNum > limit
    ? `Enter a whole number from 1 to ${limit}.` : null;
  const dirty = !!view && !!draft && (JSON.stringify({ ...draft, max_notes_length: lengthNum }) !== JSON.stringify(view.rules));

  if (!view || !draft) {
    return (
      <>
        <Header />
        <ErrorBanner message={error} />
        {!error && <p className="muted">Loading the current rules</p>}
      </>
    );
  }

  const update = (patch: Partial<Rules>) => { setDraft({ ...draft, ...patch }); setNotice(null); };

  const save = async () => {
    setSaving(true); setError(null);
    try {
      load(await api.saveRules({ ...draft, max_notes_length: lengthNum }));
      setNotice('Saved. Click "Run collector" to apply the new rules to the database.');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    setSaving(true); setError(null);
    try {
      load(await api.resetRules());
      setNotice('Back to the default rules. Click "Run collector" to apply them to the database.');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const discard = () => { load(view); setNotice(null); };

  return (
    <>
      <Header
        status={dirty ? <span className="pill pill-red">unsaved changes</span>
                      : <StatusPill status={view.is_default ? 'default' : 'changed'} />}
        actions={
          <>
            {dirty && <button className="btn btn-ghost" onClick={discard} disabled={saving}>Discard</button>}
            <button className="btn btn-secondary" onClick={reset} disabled={saving || (view.is_default && !dirty)}>
              Reset to defaults
            </button>
            <button className="btn btn-primary" onClick={save} disabled={saving || !dirty || !!lengthError}>
              {saving ? 'Saving…' : 'Save changes'}
            </button>
          </>
        }
      />
      <ErrorBanner message={error} />
      {notice && <div className="banner-ok" role="status">{notice}</div>}

      <div className="grid">
        <Panel span={12} title="1. Sanctioned apps per client"
               subtitle="An app on the client's list is sanctioned. Every other app, including new ones, is unsanctioned. Matching ignores case and extra spaces.">
          <div className="cfg-clients">
            {Object.keys(draft.sanctioned_apps).map(cid => (
              <ClientList key={cid} clientId={cid}
                          names={draft.sanctioned_apps[cid]}
                          defaults={view.defaults.sanctioned_apps[cid] ?? []}
                          onChange={names => update({ sanctioned_apps: { ...draft.sanctioned_apps, [cid]: names } })} />
            ))}
          </div>
          {apps.length > 0 && <Preview apps={apps} draft={draft} saved={view.rules} />}
        </Panel>

        <Panel span={6} title="2. Missing risk_score" subtitle="What to store when the API sends null or a value that is not a number.">
          <div className="cfg-options">
            <RiskOption value="null" current={draft.missing_risk} isDefault={view.defaults.missing_risk === 'null'}
                        title="Store NULL (unknown)"
                        body="Keeps the truth: we do not know the risk. Averages skip it. This is the default."
                        onPick={v => update({ missing_risk: v })} />
            <RiskOption value="worst_case" current={draft.missing_risk} isDefault={view.defaults.missing_risk === 'worst_case'}
                        title="Store 100 (assume worst case)"
                        body="Treats an unknown app as high risk, so it shows up in risk reports."
                        onPick={v => update({ missing_risk: v })} />
          </div>
          <p className="muted small cfg-foot">Storing 0 is not offered. 0 means "no risk", and an app we know nothing about is not safe.</p>
        </Panel>

        <Panel span={6} title="3. raw_notes" subtitle="Notes are always cleaned, then cut to this length.">
          <label className="cfg-field">
            <span className="label">Maximum length</span>
            <span className="cfg-input-row">
              <input className={`input num-input ${lengthError ? 'input-bad' : ''}`} inputMode="numeric"
                     value={lengthText} onChange={e => { setLengthText(e.target.value.trim()); setNotice(null); }}
                     aria-invalid={!!lengthError} aria-describedby="len-help" />
              <span className="muted">characters (1 to {limit}, default {view.defaults.max_notes_length})</span>
            </span>
            <span id="len-help" className={lengthError ? 'red-text small' : 'muted small'}>
              {lengthError ?? `The assignment requires ${limit} or fewer, so it cannot go higher.`}
            </span>
          </label>
          <ul className="cfg-checks">
            <li>Control characters (like the bell character <code>\x07</code>) are removed</li>
            <li>Repeated spaces and line breaks become one space</li>
            <li>Emojis and other languages are kept</li>
          </ul>
          <NotesExample apps={apps} length={lengthError ? null : lengthNum} />
        </Panel>
      </div>
    </>
  );
}

function Header({ status, actions }: { status?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="toolbar">
      <div>
        <h1>Configuration {status}</h1>
        <p className="muted">The normalisation rules. They start at the assignment defaults. Changes are used on the next run.</p>
      </div>
      {actions && <div className="toolbar-controls">{actions}</div>}
    </div>
  );
}

function ClientList({ clientId, names, defaults, onChange }: {
  clientId: string; names: string[]; defaults: string[]; onChange: (names: string[]) => void;
}) {
  const [text, setText] = useState('');
  const [msg, setMsg] = useState<string | null>(null);
  const defaultKeys = new Set(defaults.map(key));
  const removed = defaults.filter(d => !names.some(n => key(n) === key(d)));

  const add = () => {
    const name = clean(text);
    if (!name) return;
    if (name.length > 100) { setMsg('Use 100 characters or fewer.'); return; }
    if (names.some(n => key(n) === key(name))) { setMsg(`${name} is already on the list.`); return; }
    onChange([...names, name]);
    setText(''); setMsg(null);
  };

  return (
    <div className="cfg-client">
      <div className="cfg-client-head">
        <span className="mono strong">{clientId}</span>
        <span className="muted small">{names.length} sanctioned</span>
      </div>
      <div className="cfg-chips">
        {names.length === 0 && <span className="muted small">No apps. Every app will be unsanctioned for {clientId}.</span>}
        {names.map(n => (
          <span key={n} className={`chip chip-edit ${defaultKeys.has(key(n)) ? '' : 'chip-new'}`}>
            {n}
            <button aria-label={`Remove ${n}`} onClick={() => onChange(names.filter(x => x !== n))}>×</button>
          </span>
        ))}
      </div>
      <div className="cfg-add">
        <input className="input" placeholder="Add an app name, for example Claude" value={text}
               onChange={e => { setText(e.target.value); setMsg(null); }}
               onKeyDown={e => { if (e.key === 'Enter') add(); }} aria-label={`Add a sanctioned app for ${clientId}`} />
        <button className="btn btn-secondary" onClick={add} disabled={!clean(text)}>Add</button>
      </div>
      {msg && <div className="red-text small">{msg}</div>}
      {removed.length > 0 && (
        <div className="small muted">
          Removed from default: {removed.join(', ')}{' '}
          <button className="link" onClick={() => onChange([...names, ...removed])}>Put back</button>
        </div>
      )}
    </div>
  );
}

function Preview({ apps, draft, saved }: { apps: MockItem[]; draft: Rules; saved: Rules }) {
  const hover = useHover();
  const clients = Object.keys(draft.sanctioned_apps);
  const classify = (rules: Rules, cid: string, name: string) =>
    (rules.sanctioned_apps[cid] ?? []).some(n => key(n) === key(name)) ? 'sanctioned' : 'unsanctioned';

  return (
    <div className="cfg-preview">
      <div className="label">Result for the 6 apps in the mock API</div>
      <table className="table compact">
        <thead>
          <tr><th>app_name</th>{clients.map(c => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {apps.map(a => (
            <tr key={a.app_id}>
              <td>{a.app_name}</td>
              {clients.map(cid => {
                const now = classify(draft, cid, a.app_name);
                const before = classify(saved, cid, a.app_name);
                return (
                  <td key={cid} {...hover(
                    <div>
                      <div className="tt-title">{a.app_name} for {cid}</div>
                      <div>Saved rules: {before}</div>
                      <div>With your edits: <b className={now === 'unsanctioned' ? 'tt-red' : ''}>{now}</b></div>
                    </div>,
                  )}>
                    <StatusPill status={now} />
                    {now !== before && <span className="small red-text cfg-changed">changes on next run</span>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RiskOption({ value, current, isDefault, title, body, onPick }: {
  value: MissingRisk; current: MissingRisk; isDefault: boolean; title: string; body: string; onPick: (v: MissingRisk) => void;
}) {
  const active = value === current;
  return (
    <label className={`cfg-option ${active ? 'active' : ''}`}>
      <input type="radio" name="missing-risk" checked={active} onChange={() => onPick(value)} />
      <span>
        <span className="strong">{title}</span>{isDefault && <span className="tag cfg-tag">default</span>}
        <span className="muted small cfg-option-body">{body}</span>
      </span>
    </label>
  );
}

function NotesExample({ apps, length }: { apps: MockItem[]; length: number | null }) {
  const longest = useMemo(() => apps.reduce<MockItem | null>((a, b) => (!a || b.raw_notes.length > a.raw_notes.length ? b : a), null), [apps]);
  if (!longest || length === null) return null;
  const cleaned = longest.raw_notes.replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, ' ').split(/\s+/).filter(Boolean).join(' ');
  const stored = Math.min(cleaned.length, length);
  return (
    <div className="cfg-example">
      <span className="mono">{longest.app_id}</span> notes: <b>{longest.raw_notes.length}</b> characters from the API,{' '}
      {cleaned.length} after cleaning, <b className={stored < cleaned.length ? 'red-text' : ''}>{stored} stored</b>
      {stored < cleaned.length ? ' (cut)' : ''}.
    </div>
  );
}
