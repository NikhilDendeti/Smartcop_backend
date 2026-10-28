# SmartCop backend

Django REST API for a police complaint system. Citizens file complaints; an AI layer suggests the
legal sections and urgency; officers triage, investigate and close cases under role-based access.
The AI only ever suggests: an officer reviews and decides.

## What is in it

| Area | Where | What it does |
|---|---|---|
| Citizens | `users/` | Login by OTP, complaints, consent, data export, notifications, evidence upload |
| Officers | `police/` | Case list, state machine, assignment, escalation, magistrate approval, notes, FIR/GD drafts |
| AI | `ai/` | OpenAI or Claude behind one interface; classification, intake chat, drafting, summaries, status assistant; evaluation harness |
| Platform | `core/` | Error format, logging, health, metrics, audit log, idempotency, storage, rate limits |

The API is under `/api/v1/` (docs at `/api/docs/`). Routes outside it are legacy, unauthenticated
and switched off in production (`LEGACY_API_ENABLED`).

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                   # then set SECRET_KEY
python manage.py migrate
python manage.py runserver
```

Local runs use SQLite, run background jobs inline (no Celery worker needed) and print login codes
to the log. Set `DEV_FIXED_OTP=123456` to always receive the same code in development.

With Docker (PostgreSQL, Redis, API and a worker): `docker compose up --build`.

## Tests

```bash
python manage.py test core users ai police     # 311 tests
ruff check .                                   # lint
coverage run manage.py test core users ai police && coverage report
```

CI (`.github/workflows/ci.yml`) runs lint, the tests on PostgreSQL and Redis with an 85% coverage
floor, migration checks, `pip-audit`, a secrets scan and a Docker build. The AI evaluation
(`ai-eval.yml`) is run by hand because it makes billable model calls.

## Choosing and checking the AI

Provider, fallback, models, budget and the kill switch are settings (`/api/v1/admin/ai/config/`),
not code. See [docs/AI_OPERATIONS.md](docs/AI_OPERATIONS.md).

## Configuration

Everything comes from environment variables; `.env.example` lists them. The ones production needs:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django signing key |
| `FIELD_ENCRYPTION_KEY` | Encrypts Aadhar numbers at rest (Fernet key; keep it safe, losing it loses the data) |
| `DATABASE_URL`, `REDIS_URL` | PostgreSQL and Redis |
| `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` | Exact hosts and the frontend origin |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Whichever providers you use |
| `SMS_BACKEND` | Without one, login fails closed |
| `EVIDENCE_STORAGE`, `EVIDENCE_S3_*`, `EVIDENCE_SCANNER`, `CLAMD_HOST` | Evidence files and virus scanning |

## Docs

- [Deployment](docs/DEPLOYMENT.md) · [Runbook](docs/RUNBOOK.md) · [AI operations](docs/AI_OPERATIONS.md)
- [What happens when something is down](docs/DEGRADATION.md) · [Launch checklist](docs/LAUNCH_CHECKLIST.md)
