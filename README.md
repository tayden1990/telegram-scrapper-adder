# Telegram Scraper & Adder (Commercial-grade scaffold)

Production-grade scaffold for exporting members and inviting/messaging via Telegram. FastAPI + Telethon, multi-account sessions, per-account proxies/devices, rate limits/quotas, resilient worker, and an HTMX-powered admin UI.

Important: Respect Telegram ToS and local laws. Use only with consent. Bulk adding can trigger restrictions/bans.

## Features
- Admin web UI (HTMX): jobs table with filters (including Canceled), Run Now, Cancel Selected, Cancel All
- Per-job account selection: restrict which accounts are allowed to run a job
- Error visibility: failure/skip reasons shown in the Jobs table
- Inbox tab: pick an account and view its recent incoming messages
- Multi-account sessions (Telethon `.session` files in `sessions/`)
- Per-account proxy and device model; global proxy fallback
- Scraping with filters (recency, skip bots/admins)
- Detailed scraping (optional): bio, last seen, language, and visible phone numbers
- Export scraped members to CSV (Download CSV button)
- Adding/messaging with randomized delays and per-account quotas
- Central rate limiter; resilient to FloodWait/PeerFlood and ServerError -500 with backoff
- Persistent queue (SQLite via SQLModel + Alembic)
- Prometheus metrics, structured logging, CLI helpers

## Quick start (Windows PowerShell)
1) Create venv and install deps

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2) Configure environment

```powershell
Copy-Item .env.example .env
# Edit .env and set TELEGRAM_API_ID/TELEGRAM_API_HASH and SECRET_KEY
```

3) Initialize/upgrade database

```powershell
python -m alembic upgrade head
```

4) Login at least one account (interactive)

```powershell
python -m app.cli.login
```

5) Start the API and Worker (two terminals)

```powershell
# Terminal A (API)
uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal B (Worker)
python -m app.workers.worker
```

Then open http://127.0.0.1:8000 in your browser.

## Web UI highlights
- Dashboard: enqueue add/messaging jobs; pick which accounts may run the job
- Jobs: filter by status (including Canceled), Run Now, Cancel Selected, Cancel All; view error reasons
- Inbox: select an account to view incoming messages; if you see an AuthKeyNotFound warning, log in that account first from Accounts

## How it works (architecture)
- FastAPI serves the admin UI, API endpoints, and metrics. HTMX powers partial updates (live jobs table, overview, inbox).
- A background worker (`python -m app.workers.worker`) continuously picks due jobs from the SQLite queue and executes them.
- Each job can be restricted to a subset of accounts; the worker respects those constraints and account quotas.
- Telethon clients are created per account using its exact `.session` path, with optional per-account proxy and device model.
- Rate limiter + per-account quota protect against FloodWait/PeerFlood; transient Telegram ServerError (-500) is retried with backoff.
- Alembic manages schema migrations; SQLModel stores jobs, accounts, admins.

## Using the Web UI
1) Onboarding: Check readiness (SECRET_KEY, API ID/HASH, sessions dir, at least one account, worker heartbeat).
2) Accounts: Admin → Accounts → Login to add a phone; enter code (and 2FA if asked). A session file is created in `SESSIONS_DIR`.
3) Dashboard Enqueue:
	- Destination: target group/channel (e.g., `@mygroup`).
	- Targets: one `@username` or phone per line; mixed is supported.
	- Restrict to selected accounts: tick the accounts allowed to process the job.
	- Submit; watch it appear in Jobs.
4) Upload: Pick a CSV or TXT (first column used), optionally restrict accounts, enqueue.
5) Scrape: Scrape members from a public source; filter as needed; optionally check “Include full profile” to pull richer fields (bio, common chats, status, language, and phone if visible per user privacy); Download CSV for the detailed results; enqueue to destination with optional account restriction.
6) Message: Provide targets and one or more message lines; enqueues a "message" job batch.
7) Jobs: Use tabs/filters; Run Now to prioritize; Cancel Selected/All to stop queued/in-progress jobs; see error reasons inline.
8) Inbox: Select an account to view recent incoming messages; search by text/peer/sender; paginate; re-login if session invalid.
9) Settings: Update API keys, proxies, sessions dir, rate/ quota limits; saved back to `.env`.
10) Metrics: `/metrics` (Prometheus) and `/health` for health checks.

## Using the CLI
Scrape to CSV:

```powershell
python -m app.cli.scrape scrape --source "somepublicgroup" --limit 1000 --query "filter" --out data/members.csv
```

Add from CSV to a destination (single-session, direct run):

```powershell
python -m app.cli.add add --dest "@mygroup" --infile data/members.csv --per-account 25 --min-sleep 3 --max-sleep 9
```

Log in an account (interactive):

```powershell
python -m app.cli.login
```

Tip: For long/large operations, prefer the web UI queue + background worker.

## Using the HTTP API
Set `API_KEY` in `.env` and pass it via `X-API-Key` header.

Enqueue via API:

```powershell
$headers = @{ 'X-API-Key' = 'YOUR_API_KEY' }
$body = @{ dest = '@mygroup'; usernames = @('user1','user2') } | ConvertTo-Json
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/jobs/enqueue' -Method Post -Headers $headers -ContentType 'application/json' -Body $body
```

List jobs (optionally `?status=queued`):

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/jobs?status=queued' -Headers $headers
```

Programmatic scrape:

```powershell
$payload = @{ source = 'somepublicgroup'; limit = 500; query = ''; include_full = $true } | ConvertTo-Json
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/scrape' -Method Post -Headers $headers -ContentType 'application/json' -Body $payload
```

## Job lifecycle and statuses
- queued → in_progress → done
- queued → in_progress → failed (error captured)
- queued → in_progress → skipped (with reason)
- queued → canceled (via UI; worker skips)

The worker retries transient errors (ServerError -500 and some RPC errors) with exponential backoff and honors FloodWait/PeerFlood cooldowns.

## Rate limits, quotas, and proxies
- RATE_LIMIT_MAX / RATE_LIMIT_WINDOW: central throttle across actions.
- QUOTA_PER_ACCOUNT_MAX / QUOTA_PER_ACCOUNT_WINDOW: cap actions per account over time.
- Per-account proxy (HTTP/SOCKS) and device string can be configured; a global proxy acts as fallback.

## Sessions and login
- Sessions live in `SESSIONS_DIR` as Telethon `.session` files.
- Each account stores the exact session path; the worker and Inbox use that to avoid mismatches.
- If a session expires (AuthKeyNotFound), re-login via Admin → Accounts.

Phone numbers
- Telegram only exposes a user’s phone number if their privacy settings allow your account to see it (often not). Even with detailed scraping enabled, expect most rows to have empty phone.

## Roadmap (futures)
- Inbox: improved sender resolution and filtering (DMs/chats/channels), export to CSV.
- Batch progress UI using batch_id with per-batch controls.
- Connectivity tests in Settings and per-account health checks.
- Basic unit tests for services and worker loops.

## Contributing and CI
- See CONTRIBUTING.md for setup, style (ruff + black), and PR tips.
- CI runs lint and format checks on pushes/PRs via GitHub Actions.

## License
MIT — see LICENSE.

## Environment
See `.env.example` for all keys:
- SECRET_KEY: app/session secret
- TELEGRAM_API_ID / TELEGRAM_API_HASH: from https://my.telegram.org
- DATABASE_URL: defaults to `sqlite+aiosqlite:///./app.db`
- SESSIONS_DIR: folder for `.session` files (default `./sessions`)
- Optional: HTTP_PROXY / SOCKS_PROXY, rate/ quota limits, LOG_LEVEL, admin defaults, API_KEY for HTTP API

## Security
- Keep sessions private. Prefer dedicated accounts and dedicated proxies.
- Store secrets in `.env` or a secret manager. Do not commit real credentials.

## Legal
For educational use. You are responsible for compliance with Telegram policies and applicable laws.

## Troubleshooting
- sqlite3.OperationalError: no such column: addjob.kind
	- Cause: database schema is behind the latest code.
	- Fix:
		```powershell
		python -m alembic upgrade head
		```
	- Optional: verify version/columns
		```powershell
		python -c "import sqlite3; print(sqlite3.connect('app.db').execute('select version_num from alembic_version').fetchall())"
		python -c "import sqlite3, json; c=sqlite3.connect('app.db'); cols=[r[1] for r in c.execute('PRAGMA table_info(addjob)')]; print(json.dumps(cols))"
		```
- Inbox shows AuthKeyNotFound
	- The selected account isn’t logged in on this machine. Use Accounts to log in.
- ServerError: -500
	- Transient Telegram issue; the worker auto-retries with backoff.

## Author & Contact
Taher Akbari Saeed

- Email: taherakbarisaeed@gmail.com
- GitHub: https://github.com/tayden1990
- Telegram: https://t.me/tayden2023
- ORCID: https://orcid.org/0000-0002-9517-9773

Affiliation: Postgraduate Student in Hematology and Blood Transfusion, Department of Oncology, Hematology, and Radiotherapy, Institute of Postgraduate Education, Pirogov Russian National Research Medical University (RNRMU), Russia

