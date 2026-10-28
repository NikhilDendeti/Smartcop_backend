# Runbook

What to do when an alert fires. Each heading matches a link in `deploy/prometheus-alerts.yml`.
First, find the request: every response carries `X-Request-ID`, and every log line and error
report is tagged with it.

## API not ready

`/ready/` returns which dependency failed (`database` or `cache`).

- **database**: check the database host, connections and disk. The app reconnects on its own once it
  is back. Do not restart web servers repeatedly; that adds load.
- **cache** (Redis): sign-ins stop (login codes cannot be rate-limited, so they are refused with a 503
  on purpose) and background jobs stop. People already signed in keep working. Restore Redis, then run
  `python manage.py reassess_pending`.

## AI kill switch

On means no model is called and every new complaint is flagged for manual triage. It is a deliberate
control (`PATCH /api/v1/admin/ai/config/ {"kill_switch": false}`), so first find out who turned it on and
why (`update_ai_config` entries in the audit log). Officers keep working from the review queue.

## AI failures

1. Look at `GET /api/v1/admin/ai/usage/?days=1`: which provider and which status (timeout,
   rate_limited, unavailable, auth, invalid_output).
2. `auth`: a key was revoked or expired. Rotate it in the secret store and redeploy.
3. `unavailable` / `timeout` / `rate_limited`: the vendor is struggling. The circuit breaker already
   skips it for 60 seconds at a time. If a fallback provider is set, traffic is moving there (that is
   the `AIFallbackInUse` alert). If none is set, set one now with `PATCH .../ai/config/`.
4. `invalid_output`: usually a prompt or model change. Roll the model back, or run
   `python manage.py run_ai_eval` against the candidate before trying again.
5. Complaints filed meanwhile are safe: they sit in the officer review queue marked "AI unavailable".

## AI budget

At 80% the alert warns; at 100% the AI stops (complaints go to manual triage). To continue, raise
`monthly_budget_usd` through the config API after someone with authority agrees. Check whether the
spike is real use or a loop: the usage report breaks calls down by task.

## Analysis backlog

A complaint has waited too long for its AI analysis, so the worker is down or stuck.

1. Is the worker process running? Restart it. Is Redis up?
2. `python manage.py reassess_pending --older-than-minutes 1` re-queues everything stuck.
3. Complaints are never lost while waiting; officers can already see and triage them.

## Security events

Many `access_denied` or `login_failed` events in an hour.

1. Query the audit log by `actor`, `ip_address` and `resource_id` for the busiest source.
2. Repeated failed logins for one number: someone is guessing codes. The limit is 10 tries an hour per
   number; consider blocking the IP at the edge.
3. A signed-in user hitting many forbidden pages: check whether it is a misconfigured role (an officer
   with no active station) or probing.
4. Suspected token theft: replaying a used refresh token already revokes that whole login. To cut off
   a user entirely, change their role or delete their refresh tokens.

## Handling a data request

- **Export**: the citizen can download their own data at `GET /api/v1/me/export/`.
- **Erasure**: `python manage.py anonymize_user <user-id>` shows what would change; add `--confirm` to
  do it. Complaints are kept (police records have their own retention rules) but no longer name the
  person. Whether a request must be honoured is a legal decision; get it from the data protection
  officer first.

## Rotating secrets

- `SECRET_KEY` / `JWT_SIGNING_KEY`: signs tokens, so changing it signs everyone out. Do it in a quiet period.
- `FIELD_ENCRYPTION_KEY`: list the new key first and keep the old one after it, comma-separated
  (`new,old`). New writes use the new key; old data stays readable. Re-save records, then drop the old key.
- Provider API keys: add the new one, redeploy, then revoke the old one at the vendor.
