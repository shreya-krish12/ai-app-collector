# Multi-Tenant AI App Collector

An async Python collector that reads AI app usage records from a paginated mock API, classifies
each app per client (`acme`, `vontier`), and stores the results idempotently in SQLite.
A small dashboard shows each step.

## How the requirements are met

| Requirement | Code | How |
|---|---|---|
| Mock API with 2 pages (`items` + `next_cursor`) | `app_collector/api/upstream.py` | 3 apps per page; page 1 returns `next_cursor: "page-2"`, page 2 returns `null` |
| Page 2: 429 + `Retry-After`, then 200 | `upstream.py` | First request for page 2 gets `429` with `Retry-After: 1`; the retry gets `200` |
| 650-char `raw_notes` and `null` `risk_score` | `upstream.py` | The `otter` record |
| Two clients, own `sanctioned_apps` | `app_collector/config.py` | `acme`: ChatGPT, GitHub Copilot. `vontier`: Claude, Gemini, GitHub Copilot |
| Async ingestion and 429 backoff | `app_collector/api/client.py` | `httpx.AsyncClient`; waits for `Retry-After` (falls back to exponential backoff); both clients run concurrently |
| Per-client normalisation | `app_collector/collector/normalizer.py` | `classification` from that client's list; `risk_score: null` is stored as `NULL`, **not 0** (unknown is not "no risk"); `raw_notes` cleaned and cut to 500 |
| Idempotent persistence | `app_collector/storage/db.py` | `UNIQUE(client_id, app_id)` + `INSERT ... ON CONFLICT DO UPDATE`. A re-run updates the row and increments `times_collected` |
| Tests | `tests/` | pagination, 429 retries, multi-tenant isolation, truncation, idempotency |

### Two modes, same code

| Mode | How the API is reached |
|---|---|
| **Mock** | `httpx.MockTransport`, inside Python, no network |
| **Real-time** | Real HTTP to the FastAPI mock server at `http://127.0.0.1:8000/upstream` |

Only the transport differs. The client, normaliser, database code and data are shared.

## Setup

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
cd frontend
npm install
```

## Run

```powershell
# Terminal 1: backend (http://127.0.0.1:8000, API docs at /docs)
venv\Scripts\activate
python api_server.py
```

```powershell
# Terminal 2: dashboard (http://localhost:3000)
cd frontend
npm run dev
```

The dashboard walks through five tabs: **Mock API** (the data, plus a "send a request" panel that
shows the 429), **Live collection**, **Database**, **Analytics**, and **Tests**.

To run without the dashboard:

```powershell
python main.py               # mock mode
python main.py --mode real   # real-time mode (needs api_server.py running)
```

Run it twice: the second run shows `0 new, 12 updated`.

## Look at the data in DBeaver

SQLite is a file, so there is **no host or port**.

1. In DBeaver, go to **Database** → **New Database Connection** → **SQLite**.
2. Set **Path** to `D:\INTERN\SENNOVATE\app_collector.db`, then click **Finish**.
3. Open `app_usage_records` and press F5 after each run.

To check there are no duplicates (this should return 0 rows):

```sql
SELECT client_id, app_id, COUNT(*) FROM app_usage_records
GROUP BY client_id, app_id HAVING COUNT(*) > 1;
```

To use PostgreSQL instead, set
`DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/app_collector`. DBeaver then connects
to port 5432. The same upsert works unchanged.

## Tests

```powershell
pytest
pytest --cov=app_collector
```

55 tests run in about 4 seconds. Retry tests use a fake `sleep`, so they check the exact wait
without actually waiting. Every test uses its own temporary database.

| File | What it proves |
|---|---|
| `test_pagination.py` | both pages fetched in order, cursor sent, stops on `null` |
| `test_retry.py` | 429 then 200, `Retry-After` respected, backoff, retry limit, 4xx fails fast |
| `test_normalization.py` | 650 → 500 chars, control characters removed, `null` risk stays `NULL` |
| `test_idempotency.py` | re-run updates without duplicating; `created_at` kept |
| `test_multi_tenant.py` | same app sanctioned for one client and unsanctioned for the other; clients isolated |
| `test_modes.py` | mock and real-time produce identical rows |
| `test_api.py` | the dashboard's API |

## Database tables

`app_usage_records`: `client_id`, `app_id`, `app_name`, `classification`, `risk_score`, `users`,
`raw_notes`, `notes_truncated`, `times_collected`, `created_at`, `updated_at`.
Unique on `(client_id, app_id)`.

`collector_runs`: one row per run with its summary.
