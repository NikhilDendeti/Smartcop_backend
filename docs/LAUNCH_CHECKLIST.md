# Launch checklist

This system holds police and citizen data. Do not skip the "people" items because the code is ready.
`[x]` marks what the repository already provides; `[ ]` needs a person or a decision.

## Decisions to make first

- [ ] SMS provider for login codes (set `SMS_BACKEND`); nothing can sign in without one
- [ ] Primary and fallback AI provider, and the models per task (see `docs/AI_OPERATIONS.md`)
- [ ] Hosting platform, regions, and who is on call
- [ ] Evidence storage (S3-compatible) and a virus scanner (ClamAV)
- [ ] Which roles may do what, confirmed by someone who knows station procedure (SHO scope, escalation, four-eyes approval of FIRs)
- [ ] Data retention periods and the erasure policy, agreed with the data protection officer

## Legal and compliance

- [ ] A legal reviewer loads and signs off the BNS/IPC section table and the cognizable flags
- [ ] A privacy notice and the consent wording shown to citizens (policy version recorded with each consent)
- [ ] Data protection law review (DPDP Act 2023): purpose, retention, breach process, cross-border processing by AI vendors
- [ ] A decision on whether complaint text may go to each AI vendor, and the vendor terms checked (no training on your data)
- [ ] A breach response plan with named people

## Security

- [x] Secrets from the environment; production refuses unsafe settings
- [x] OTP login with hashed, expiring, attempt-limited codes; rotating refresh tokens
- [x] Role-based access with station scoping; automated audit of every route
- [x] Aadhar numbers encrypted at rest; masked for officers; PII masked in logs, error reports and model prompts
- [x] Audit log of logins, views, changes and denials
- [ ] Rotate the Django and OpenAI keys that were committed or printed earlier, and scrub them from git history
- [ ] Independent penetration test or security review
- [ ] Turn on a WAF / rate limiting at the edge; HTTPS everywhere
- [ ] Keep `LEGACY_API_ENABLED` off; migrate the frontend to `/api/v1`

## Operations

- [x] Image build, CI with PostgreSQL and Redis, coverage floor, dependency and secret scans
- [ ] Production environment, secrets and worker deployed; `migrate` run
- [ ] Scheduled jobs set up (`reassess_pending`, `purge_expired`)
- [ ] Monitoring: Sentry DSN, Prometheus scraping `/metrics/` with `METRICS_TOKEN`, alert rules loaded, a person receiving the pages
- [ ] Backups running and a restore drill done once
- [ ] Load test on staging (`loadtests/locustfile.py`) against the expected number of users

## Quality of the AI

- [ ] Legal reviewer extends the evaluation set (especially regional languages) and signs off the labels
- [ ] `run_ai_eval` meets the gates on the provider you will use
- [ ] Officers briefed on the review queue and on why AI output is only a suggestion

## Pilot

- [ ] One station, a fixed start date and a named owner
- [ ] Officers trained; citizens told that AI helps and that they can decline it
- [ ] Weekly review of the usage report, the override rate and any complaints about the system
- [ ] Clear criteria to widen, pause or stop the pilot
