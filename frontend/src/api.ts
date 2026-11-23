export type Mode = 'mock' | 'real';
export type Classification = 'sanctioned' | 'unsanctioned';

export interface ClientStats {
  client_id: string;
  status: 'waiting' | 'running' | 'completed' | 'failed';
  pages: number;
  received: number;
  inserted: number;
  updated: number;
  rejected: number;
  retries: number;
  truncated: number;
  missing_risk: number;
  sanctioned: number;
  unsanctioned: number;
  error: string | null;
}

export type Totals = Omit<ClientStats, 'client_id' | 'status' | 'error'>;

export interface RunEvent {
  seq: number;
  ts: string;
  level: 'info' | 'warning' | 'error';
  client_id: string | null;
  message: string;
}

export interface Run {
  id: string;
  mode: Mode;
  status: 'running' | 'completed' | 'partial' | 'failed';
  started_at: string;
  finished_at: string | null;
  error: string | null;
  summary: { totals: Totals; clients: Record<string, ClientStats> } | null;
  events?: RunEvent[];
}

/** One row of app_usage_records, same column names as in the database. */
export interface AppRecord {
  id: number;
  client_id: string;
  app_id: string;
  app_name: string;
  classification: Classification;
  risk_score: number | null;
  users: number | null;
  raw_notes: string | null;
  notes_truncated: boolean;
  times_collected: number;
  created_at: string;
  updated_at: string;
}

export interface MockItem {
  app_id: string;
  app_name: string;
  users: number;
  risk_score: number | null;
  raw_notes: string;
}

export interface MockData {
  endpoint: string;
  retry_after_seconds: number;
  clients: {
    client_id: string;
    sanctioned_apps: string[];
    page_1: { items: MockItem[]; next_cursor: string | null };
    page_2: { items: MockItem[]; next_cursor: string | null };
  }[];
}

export interface PlaygroundResponse {
  status_code: number;
  headers: Record<string, string>;
  body: unknown;
}

export interface ClientSummary {
  client_id: string;
  apps: number;
  sanctioned: number;
  unsanctioned: number;
  missing_risk: number;
  truncated: number;
  avg_risk: number | null;
  users: number;
}

export interface Config {
  default_mode: Mode;
  upstream_base_url: string;
  clients: { client_id: string; sanctioned_apps: string[] }[];
  max_retries: number;
  database: { type: string; file: string | null; url: string };
}

export type MissingRisk = 'null' | 'worst_case';

export interface Rules {
  sanctioned_apps: Record<string, string[]>;
  missing_risk: MissingRisk;
  max_notes_length: number;
}

export interface RulesView {
  rules: Rules;
  defaults: Rules;
  is_default: boolean;
  max_notes_limit: number;
  saved_to: string | null;
}

export interface TestCase {
  module: string;
  name: string;
  classname: string;
  duration: number;
  status: 'passed' | 'failed' | 'error' | 'skipped';
  message: string | null;
}

export interface TestResult {
  status: 'passed' | 'failed' | 'error';
  started_at: string;
  duration?: number;
  counts?: { passed: number; failed: number; error: number; skipped: number; total: number };
  tests?: TestCase[];
  coverage?: { percent: number; files: { file: string; statements: number; missing: number; percent: number }[] } | null;
  output_tail?: string;
  error?: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) } });
  } catch {
    throw new Error('Cannot reach the API server. Start it with: python api_server.py');
  }
  if (!response.ok) {
    let body: any = null;
    try { body = await response.json(); } catch { /* not JSON */ }
    if (body?.detail) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail));
    if (response.status >= 500) {
      throw new Error(`The API server is not running or failed (HTTP ${response.status}). Check the terminal running "python api_server.py".`);
    }
    throw new Error(`Request failed: HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

const qs = (params: Record<string, string | number | undefined | null>) => {
  const s = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&');
  return s ? `?${s}` : '';
};

export const api = {
  config: () => request<Config>('/api/config'),
  mockData: () => request<MockData>('/api/mock-data'),
  playground: (clientId: string, cursor?: string) =>
    request<PlaygroundResponse>(`/api/playground/apps${qs({ client_id: clientId, cursor })}`),
  resetPlayground: () => request('/api/playground/reset', { method: 'POST' }),
  startRun: (mode: Mode) => request<Run>('/api/runs', { method: 'POST', body: JSON.stringify({ mode }) }),
  runs: (limit = 20) => request<Run[]>(`/api/runs${qs({ limit })}`),
  run: (id: string, after = 0) => request<Run>(`/api/runs/${id}${qs({ after })}`),
  records: (clientId?: string) => request<AppRecord[]>(`/api/records${qs({ client_id: clientId })}`),
  clearRecords: () => request<{ deleted: number }>('/api/records', { method: 'DELETE' }),
  summary: () => request<{ clients: ClientSummary[]; runs: Run[] }>('/api/summary'),
  runTests: () => request<TestResult>('/api/tests', { method: 'POST' }),
  lastTests: () => request<TestResult | null>('/api/tests'),
  rules: () => request<RulesView>('/api/rules'),
  saveRules: (rules: Rules) => request<RulesView>('/api/rules', { method: 'PUT', body: JSON.stringify(rules) }),
  resetRules: () => request<RulesView>('/api/rules/reset', { method: 'POST' }),
};

export const fmt = {
  num: (n: number | null | undefined) => (n === null || n === undefined ? '—' : n.toLocaleString('en-US')),
  date: (iso: string | null | undefined) =>
    iso ? new Date(iso).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—',
  time: (iso: string) => new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
  seconds: (start: string, end: string | null) =>
    end ? `${((new Date(end).getTime() - new Date(start).getTime()) / 1000).toFixed(1)} s` : '—',
  mode: (m: Mode) => (m === 'mock' ? 'Mock' : 'Real-time'),
};
