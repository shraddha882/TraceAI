# TraceAI

## Workspace access

Anyone can register at `/accounts/signup/`, then sign in at `/accounts/login/`. Registration creates an ordinary active account with a validated, hashed password; it does not grant staff or administrator access. Reviews, PR jobs, reports, incidents and evidence are private to their owner. Legacy records without an owner remain visible only to staff. Staff can manage records through Django administration according to their permissions.

Anonymous users are redirected to sign in; background status endpoints return HTTP 401. Sign out uses POST with CSRF protection. Production HTTPS/session-cookie configuration and login rate limiting remain deployment work.

Django, Django REST Framework, HTML, Tailwind CSS and vanilla JavaScript code review and incident investigation. Static review and evidence analysis work without an LLM API key.

## Local setup

Use Python 3.14 and PostgreSQL 17. Create a PostgreSQL login and a database owned by that login. The development login needs `CREATEDB` to run Django's tests; a deployed application login should not have this privilege or superuser access.

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

For an existing checkout, preserve your current `.env`. Set `POSTGRES_PASSWORD` to your local database password. Never commit `.env` or backups. Settings also accept environment variables, which take precedence over `.env`.

```powershell
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py test
.\venv\Scripts\python.exe manage.py runserver
```

Visit `/code-review/` or `/incidents/`. For a synthetic incident demo, run `manage.py create_demo_incident --username YOUR_USERNAME` using the virtual environment's Python. This adds an owned synthetic incident with logs, database metrics, traces, a placeholder deployment and four RCA hypotheses. Repeating the command for the same account does not duplicate records. Without `--username`, it creates a legacy staff-only demo. For the code-review showcase, upload `examples/showcase_checkout.py`; it produces five static findings without executing the example.

### Background PR reviews and RCA reports

Run a separate terminal alongside the web server:

```powershell
.\venv\Scripts\python.exe manage.py run_review_worker
```

Analyze Python Files queues a durable PostgreSQL job. The status page polls every three seconds and links to the saved report when complete. Recent jobs are accessible from Review History. Preview remains synchronous. Workers claim jobs with row locks, allowing multiple workers without duplicate claims. `--once` processes at most one PR job and one RCA job for diagnostics. GitHub is fetched at execution time, so the saved report records that commit.

Generate RCA Investigation Report also queues work using the same worker. The incident page links to recent jobs and completed reports. Repeated submissions reuse the incident's pending/running job. RCA uses saved evidence available during execution; it does not automatically fetch new telemetry or call an LLM. Failed jobs can be retried by generating a new report from the incident page. Restart the worker after updating its Python code.

If the worker stops, queued jobs remain pending. On the next worker pass, running jobs older than 15 minutes are marked failed; submit a new analysis to retry. This is recovery for interrupted jobs, not a hard process timeout. Keep the worker supervised in deployment. No Redis or LLM API is required.

## Database configuration

### Optional AI explanation

RCA generation has an unchecked-by-default AI option. Configure `OPENAI_API_KEY` and optionally `TRACEAI_AI_MODEL` (default `gpt-5`) in `.env`, then restart the web server and worker. The Responses API receives at most eight rule-generated hypothesis summaries; raw logs, source code, incident metadata and evidence titles/IDs are excluded. The model explains existing leads, without replacing deterministic findings. Returned hypothesis references are validated and rendered as escaped text with local links. This does not verify the model's reasoning: review its suggestions against the evidence.

Requests use `store=False`, a 30-second SDK timeout, no automatic retries and a bounded output budget. Provider policies still apply; `store=False` is not a promise of zero retention. Opting in can incur API charges. Missing keys, API errors, refusals, incomplete responses and invalid references leave the static report available with an explicit AI fallback status. Active jobs retain their original opt-in choice. AI applies only to new RCA reports, not PR reports or historical snapshots.

### Cross-source RCA rules

New RCA reports match database connection usage, lock waits or slow-query findings with specific error-log phrases within five minutes of each other and within the incident's existing ±15 minute window. A nearby error/slow trace is supporting context only when its service exactly matches the incident. Leads remain low-confidence because log ownership, database-to-service mapping and environment are not verified. Generic timeouts alone do not identify a database mechanism. Existing saved reports remain unchanged.

For the synthetic September 24 demo, `examples/rca_database_signals.log` supplies explicit matching log phrases for `examples/database_snapshot.json`. Attach that sample to the synthetic incident and generate a new RCA report. These are artificial test inputs, not real production evidence.

`TRACEAI_DB_BACKEND=postgresql` selects PostgreSQL. Configure `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` and `POSTGRES_SSLMODE`. Missing PostgreSQL configuration fails explicitly. The optional `sqlite` backend is available for isolated experiments; switching backends does not transfer data.

Existing local SQLite data is backed up under the ignored `backups/` directory during the initial PostgreSQL transfer. Keep backups private: they contain submitted code and incident evidence. The original `db.sqlite3` remains a historical copy after switching to PostgreSQL; it does not receive subsequent updates.

On another development or deployment host, configure that host's database credentials and run migrations. Production deployment additionally requires secret-key configuration, disabled debug mode, allowed hosts, HTTPS, static assets, and an application server; the current settings are for local development.


