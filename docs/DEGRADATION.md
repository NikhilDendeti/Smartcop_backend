# When something is down

The rule: a failure may slow a feature down or switch it to a manual path, but it must never
quietly make a case look less serious, lose a complaint, or let someone in without checks.

| What fails | What still works | What changes | Where it is tested |
|---|---|---|---|
| The AI provider (outage, timeout, rate limit) | Filing complaints, all officer work | Retries, then the fallback provider, then the complaint is marked "AI unavailable" and flagged for manual triage. Serious-offence keywords still raise urgency. | `ai/test_gateway.py`, `ai/test_classification.py` |
| The main provider keeps failing | Everything | The circuit breaker skips it for 60 s and traffic goes to the fallback | `ai/test_gateway.py` |
| AI budget spent / kill switch | Everything except AI | No model calls; complaints go to manual triage | `ai/test_gateway.py`, `ai/test_ops.py` |
| The job queue (Redis broker) | Filing complaints | The analysis stays "pending" and is retried by `reassess_pending` | `ai/test_classification.py` |
| The background worker | Filing complaints, officer work | Analyses wait; the backlog alert fires | alert in `deploy/prometheus-alerts.yml` |
| Redis (cache) | People already signed in, complaints, officer work | New sign-ins are refused with 503 (login limits cannot be enforced); the AI circuit breaker and AI rate limit stop tracking and let calls through | `core/test_resilience.py` |
| The database | Liveness probe | `/ready/` reports 503; requests fail until it returns | `core/test_resilience.py` |
| The SMS provider | Everyone already signed in | New sign-ins answer 503; no code is stored for a message that was not sent | `users/test_auth.py` |
| No SMS provider configured | Everyone already signed in | Sign-in fails closed (503) | `users/test_auth.py` |
| The virus scanner | Everything else | New evidence stays "pending/failed" and cannot be downloaded | `users/test_evidence.py` |
| Object storage | Everything else | Evidence upload and download fail; nothing else is affected | n/a (S3 not run here) |

Backups and restore: see `docs/DEPLOYMENT.md`. Targets used for planning: recover within 4 hours
(RTO), losing at most 24 hours of data (RPO). Change them to match what the station can accept.
