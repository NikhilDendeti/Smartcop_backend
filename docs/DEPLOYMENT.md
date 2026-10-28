# Deployment

The project ships as one container image with three roles. Any platform that runs containers
(a VM with Docker, ECS, Kubernetes, Render, Railway and similar) can host it; nothing here is tied to one.

## Processes

| Role | Command | Scale |
|---|---|---|
| Web | `gunicorn Smartcop_backend.wsgi:application --bind 0.0.0.0:8000` (the image default) | 2+ for availability |
| Worker | `celery -A Smartcop_backend worker --loglevel=info` | 1+; runs the AI analysis of new complaints |
| Release step | `python manage.py migrate --noinput` | once per release, before the new web starts |

Scheduled jobs (cron, or your platform's scheduler):

| Job | Command | How often |
|---|---|---|
| Re-queue stuck AI analyses | `python manage.py reassess_pending` | every 5 minutes |
| Remove expired operational data | `python manage.py purge_expired` | daily |

Dependencies: PostgreSQL 16 and Redis 7 (cache, rate limits, job queue). Optional: ClamAV (`clamd`)
for evidence scanning, an S3-compatible bucket for evidence, Sentry, Prometheus.

## Configuration

Set everything as environment variables (see `.env.example`). Production refuses to start if
`ALLOWED_HOSTS` is empty or `*`, `CORS_ALLOWED_ORIGINS` is empty, `DATABASE_URL` is SQLite, or
`FIELD_ENCRYPTION_KEY` is missing. Generate keys with:

```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"        # SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"        # FIELD_ENCRYPTION_KEY
```

Store them in your platform's secret manager, not in the repository or the image.

Before the first real login works you must choose and configure an SMS provider (`SMS_BACKEND`).
Without one the login endpoint answers 503 by design.

## Releasing

1. Merge to `main`; CI must be green.
2. Tag a version (`git tag v1.2.0 && git push --tags`). `release.yml` builds and publishes
   `ghcr.io/<owner>/<repo>:1.2.0`.
3. Deploy that image to staging first and run the checks below.
4. Run the release step (`migrate`), then roll out web and worker.
5. Watch `/ready/`, the error rate and the AI failure rate for 15 minutes.

Post-deploy checks: `GET /health/` and `GET /ready/` return 200; sign in as a test citizen and
officer; file a test complaint and confirm its AI status leaves `pending`.

## Migrations: keep rollbacks possible

- Deploy the migration first, then the code that needs it. Never ship code that needs a migration
  that has not run.
- Make schema changes backwards compatible for one release: add columns as nullable or with a
  default; stop writing a column in one release and drop it in the next.
- Data migrations (such as the Aadhar encryption) must have a working reverse, and must be tried on
  a copy of production data first.

## Rolling back

1. Redeploy the previous image tag (web and worker).
2. Only if the release included a migration the old code cannot run against: `python manage.py
   migrate <app> <previous migration>` first. Restore from backup instead if data was changed
   irreversibly.
3. Record what happened in the runbook.

## Backups and restore

Back up PostgreSQL daily and keep point-in-time recovery if your host offers it. Back up the evidence
bucket (versioning on) and **`FIELD_ENCRYPTION_KEY`** separately and securely: without the key the
encrypted columns cannot be read.

Dump and restore with the standard tools:

```bash
pg_dump --format=custom --no-owner "$DATABASE_URL" > smartcop.dump
createdb smartcop_restore
pg_restore --no-owner --dbname smartcop_restore smartcop.dump
```

Run a restore drill every quarter: restore the latest backup into a scratch database, start the app
against it, and confirm a known complaint can be read. Target: recover to within 24 hours of data
(RPO) in under 4 hours (RTO) unless you decide otherwise.

## Securing the edge

- Terminate HTTPS at the load balancer; the app trusts `X-Forwarded-Proto`. Production settings turn
  on HTTP-to-HTTPS redirect, HSTS and secure cookies.
- Put a WAF or a CDN with rate limiting in front. The app has its own limits on login and AI calls,
  but they are a backstop.
- Do not expose `/metrics/` publicly; it also requires `METRICS_TOKEN`.
- Only the frontend's exact origin belongs in `CORS_ALLOWED_ORIGINS`.
- Leave `LEGACY_API_ENABLED` off.
