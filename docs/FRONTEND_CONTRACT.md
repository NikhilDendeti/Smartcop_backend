# Frontend ↔ backend contract

The single source of truth for what the frontend can call. Two sessions work from it in parallel:
the **backend** session (repo `smartcop backend`) builds and owns every endpoint, and the **frontend**
session (repo `smartcop frontend`) builds the screens.

**Rules**
1. An item marked **AVAILABLE** is live and tested. Its shape does not change without a message to the frontend and a note in the changelog at the bottom.
2. An item marked **PLANNED** has an agreed shape below but is not built yet. Build the frontend against these shapes using mocks (MSW). The backend promises to deliver exactly this shape; if it must differ, it says so in a message first.
3. If the frontend needs something that is missing or awkward, it asks the backend session (do not work around it silently, and do not edit backend files). The backend replies with a decision and updates this file.
4. The backend session messages the frontend session whenever a PLANNED item becomes AVAILABLE.

## Conventions (AVAILABLE)

- Base URL: `VITE_API_BASE_URL` (local backend: `http://localhost:8000`). All routes are under `/api/v1/`.
- Auth: `Authorization: Bearer <access token>` on everything except the three public auth routes.
- Errors, always this shape: `{"error": {"code": "...", "message": "...", "details": {...}}, "request_id": "..."}`.
  Show `message` to people; show `request_id` in a "contact support" detail. `details` holds field errors for `validation_error`.
- Error codes: `validation_error` 400 · `unauthorized` 401 · `forbidden` 403 · `consent_required` 403 · `not_found` 404 ·
  `conflict` / `invalid_transition` / `version_conflict` / `idempotency_conflict` 409 · `idempotency_key_reused` 422 ·
  `rate_limited` 429 · `internal_error` 500 · `service_unavailable` / `sms_unavailable` / `assistant_unavailable` 503.
- Lists: `{count, next, previous, results}`; query `?page=` and `?page_size=` (max 100).
- Every response has `X-Request-ID` (readable from JS).
- Create endpoints for complaints **require** an `Idempotency-Key` header (a fresh UUID per submit; reuse the same one on retry).
- Dates `YYYY-MM-DD`, times `HH:MM:SS`, timestamps ISO 8601.
- Roles (`/auth/me` → `role`): `citizen`, `head_constable`, `sub_inspector`, `sho`, `magistrate`, `admin`.
- Case statuses: `pending`, `under_review`, `assigned`, `under_investigation`, `awaiting_magistrate`, `fir_registered`, `gd_recorded`, `resolved`.
- Local login: with the backend in dev mode and `DEV_FIXED_OTP=123456`, every login code is `123456`.

## Running the backend locally (AVAILABLE)

- **Shared dev server:** the backend session keeps a server running at **`http://localhost:8001`** (set `VITE_API_BASE_URL=http://localhost:8001`). It uses a throwaway database filled with demo data and reloads by itself when backend code changes. If it is down, message the backend session. Port 8000 is taken by another project on this machine, so do not use it.
- **Demo logins** (the login code is always `123456`, there is no resend cooldown or login rate limit in this mode):

  | Phone | Who | Role |
  |---|---|---|
  | `9000000001` | Asha Citizen (has AI consent; has 3 complaints: pending, under investigation, general-diary) | `citizen` |
  | `9000000002` | Ravi Citizen (no consent yet, no complaints: use it for the consent and first-complaint flows) | `citizen` |
  | `9000000011` | Hari Head Constable (assigned 1 case) | `head_constable` |
  | `9000000012` | Sita Sub-Inspector | `sub_inspector` |
  | `9000000013` | Omar SHO | `sho` |
  | `9000000021` | Meera Magistrate | `magistrate` |
  | `9000000031` | Ajay Admin | `admin` |

- **Your own copy** (optional, e.g. for Playwright in CI): in the backend folder run `SECRET_KEY=anything API_PORT=8001 docker compose up --build`, then `docker compose exec web python manage.py seed_demo`.
- **Browser calls:** CORS allows `http://localhost:5173`, `4173`, `8080` and `3000` and the `Idempotency-Key` header.
- The AI features need real provider keys. The dev server has none, so classification answers `ai_status: "unavailable"` and the intake/assistant endpoints report `ai_available: false`. That is the right state to build the "AI is down, continue manually" screens against. Say so if you need the backend session to switch on a canned-answer mode for UI work.

## Auth (AVAILABLE)

| Call | Body | Success | Notes |
|---|---|---|---|
| `POST /auth/otp/request/` | `{phone}` | 202 `{message}` | Same answer for unknown numbers. 429 on cooldown (60 s) or limit; 503 if no SMS |
| `POST /auth/otp/verify/` | `{phone, code}` (6 digits) | 200 `{access, refresh, token_type, expires_in, user:{user_id,name,role}}` | 401 wrong/expired code; 403 account has no active role; 429 too many tries |
| `POST /auth/token/refresh/` | `{refresh}` | 200 `{access, refresh, token_type, expires_in}` | Each refresh token works once; use the new one. Reusing an old one logs the whole session out (401) |
| `POST /auth/logout/` | `{refresh}` | 204 | Needs Bearer |
| `GET /auth/me/` | | `{user_id,name,phone,email,role,designation,department,station:{station_id,name,code}\|null}` | |

Access tokens last 15 minutes, refresh tokens 7 days.

## Citizen (AVAILABLE)

- `GET /case-types/` → `[{case_type_id, name, label}]` (`name` is what complaints use: `murder`, `theft`, `crime_against_women`, `public_nuisance`).
- `POST /complaints/` (citizen, `Idempotency-Key` required) body
  `{case_type, incident_summary, location, incident_date, incident_time, station_id?, is_cognizable?(default true), accused?:[{name,description,contact_info,statement}], witnesses?:[{name,contact_info,statement}]}`
  → 201 `{message, complaint_id}`. **Station rule:** a complaint always goes to a station, otherwise no officer could see it. Send `station_id` (from `GET /stations/`). If you omit it and exactly one station is active, the server uses that one; if there are several (or none) you get 400 `validation_error` with `details.station_id`. The same rule applies to `/complaints/non-cognizable/`. A 400 does not use up the Idempotency-Key. **Do not send videos/base64 or `evidence` URLs; upload files with the evidence calls below after creating the complaint.** The AI analysis runs afterwards in the background: the complaint starts with `ai_status: "pending"`.
- `POST /complaints/non-cognizable/` same body minus accused/witnesses/is_cognizable → 201 `{message, complaint_id, status:"gd_recorded", ai_status:"pending"}`.
- `GET /complaints/mine/` → paginated `[{complaint_id, case_type, status, incident_summary, incident_date}]`.
- `GET /complaints/<id>/` → `{complaint_id, user:{...}, case_type (label), incident_summary, location, incident_date, incident_time, is_cognizable, status, ai_urgency_score, created_at, assessment:{ipc_sections, ipc_descriptions, urgency_score, model_version, generated_at}, accused[], witnesses[], evidence[]}` (404 if not yours). *Gets more fields in B5.*
- `POST /ai/assessments/` `{incident_summary}` → preview of suggested sections `{ai_status, needs_review, reasons[], act, is_cognizable, ipc_sections:{code:title}, AI_urgency_score?}`. Limited to 30/hour. *Will require AI consent in B9.*
- Consent: `GET /consents/` → `[{purpose,label,granted,policy_version,granted_at,revoked_at}]`; `POST /consents/update/` `{purpose, policy_version, granted}` → same list. Purposes: `complaint_processing`, `ai_processing`, `notifications`. AI features answer 403 `consent_required` without `ai_processing`.
- `GET /me/export/` → downloadable JSON of the citizen's own data.
- `POST /users/current-address/` `{current_address}`.
- Notifications: `GET /notifications/?unread=true` → paginated `[{notification_id,event,message,complaint_id,read,created_at}]`; `POST /notifications/<id>/read/` → 204.

### Evidence upload (AVAILABLE; citizens and officers in scope)

1. `POST /complaints/<id>/evidence-files/` `{filename, content_type, size_bytes, sha256}` (sha256 = hex of the file) →
   201 `{file_id, filename, type, content_type, size_bytes, uploaded:false, scan_status, uploaded_at, upload:{method:"PUT", url, headers}}`.
   Allowed types: jpeg, png, webp, heic, pdf; video: mp4, quicktime, **webm**; audio: mpeg, wav, mp4, **webm**, **ogg** (so a browser `MediaRecorder` recording works). Codec suffixes such as `video/webm;codecs=vp9,opus` are accepted; the server stores and returns the clean base type (`video/webm`), and `upload.headers` tells you the `Content-Type` to send with the bytes. Limits: image/pdf 25 MB, audio 50 MB, video 200 MB, 50 files per complaint.
2. Send the bytes: `PUT <upload.url>` with `upload.headers` and the file as the raw body. If `url` is relative (`/api/v1/...`), it is the API itself: prefix the base URL and also send the Bearer token. If it is absolute (cloud storage), send no Authorization header.
3. `POST /evidence-files/<file_id>/complete/` → the file row with `uploaded:true` and `scan_status` (`pending|clean|infected|failed`). 400 means the file did not match its size/checksum: upload again from step 1.
4. `GET /complaints/<id>/evidence-files/` → list of file rows. `GET /evidence-files/<file_id>/download/` → the file (or `{url, expires_in}` for cloud storage). 409 until scanned (in dev, files are released unscanned).

### AI chat and assistant (AVAILABLE, need `ai_processing` consent)

- `POST /intake/conversations/` `{language?}` → 201 `{conversation_id, disclosure}` (show the disclosure text).
- `POST /intake/conversations/<id>/messages/` `{content}` (≤ 2000 chars) → `{reply, emergency, ready, missing[], report|null, ai_available}`. When `emergency` is true, the reply already includes emergency numbers: show it prominently. When `ready`, `report` = `{incident_summary, case_type, location, incident_date, incident_time}` for the citizen to review and then submit with `POST /complaints/` themselves. `ai_available:false` means fall back to the plain form.
- `GET /intake/conversations/<id>/` → `{conversation_id, status, messages:[{role,content,at}], report}`.
- `POST /assistant/ask/` `{complaint_id, question}` → `{answer, needs_human, ai_available}`.

## Officers (AVAILABLE; roles `head_constable`, `sub_inspector`, `sho` unless noted)

- `GET /police/me/` → `{user_id,name,phone,designation,role_key,department,station}`.
- `GET /police/complaints/?status=&page=` (also magistrates: only cases routed to them) → paginated
  `[{complaint_id, user:{name,phone}, case_type, status, current_stage, ai_urgency_score, ai_status, needs_review, ipc_sections, created_at}]`.
- `GET /police/complaints/<id>/` → `{version, is_cognizable, available_transitions[], magistrate_approval:{awaiting,approved,comments}|null, escalations[], drafts[], complaint_id, user:{name,phone,aadhar(masked)}, case_type, status, description, location, created_at, current_stage, progress_timeline:[{stage,timestamp,updated_by}]}`. *Gets many more fields in B3.*
- Moving a case: `POST /police/complaints/status/` `{complaint_id, status, remarks?, version?}` → `{message, complaint_id, status, version, available_transitions}`.
  **Assigning is not a status change:** `available_transitions` never contains `assigned`, and `POST /police/complaints/status/` with `status:"assigned"` answers 409 `invalid_transition`. Use the assign action (below), which records the head constable. Always send the `version` you loaded; 409 `version_conflict` means reload. 409 `invalid_transition` carries a plain-language `message`. Only offer the buttons in `available_transitions`. Resolving needs `remarks`.
- `POST /police/complaints/assign/` `{complaint_id, head_constable_phone, notes?, version?}` (SI/SHO) · `GET /police/head-constables/` → `{status, head_constables:[{user_id,name,phone,department}]}` (SI/SHO).
- `POST /police/complaints/mark-under-investigation/` `{complaint_id, remarks?, version?}`.
- Notes `GET|POST /police/complaints/<id>/notes/` (`{note}`) · Escalations `GET|POST .../escalations/` (`{to_role: sub_inspector|sho, reason}`).
- Magistrate flow: SI/SHO `POST .../magistrate-approval/` `{comments?}`; magistrate `POST .../magistrate-decision/` `{decision: approve|reject, comments?}`.
- Drafts: `GET|POST .../drafts/` (`{document_type: fir|gd, content}`), `POST .../drafts/<draft_id>/approve/` (SI/SHO), `POST .../drafts/ai/` `{document_type}` (AI draft, always shown as "AI-generated").
- AI help: `GET .../triage/` (SI/SHO) · `POST .../summary/` · `GET /police/ai-review-queue/` · `POST .../ai-review/` `{decision: accepted|edited|rejected, sections?:{code:title}, is_cognizable?, urgency_score?, notes?}`.

## Admin (AVAILABLE; role `admin`)

- `GET|PATCH /admin/ai/config/` → `{provider, fallback_provider, canary_provider, canary_percent, models_by_task, timeout_seconds, max_retries, monthly_budget_usd, kill_switch, updated_at}`.
- `GET /admin/ai/usage/?days=7` → totals, failure rate, latency, cost, review queue size, officer override rate.

---

## PLANNED (agreed shapes; mock these until the backend says they are live)

### B1 Registration — now AVAILABLE (phone is verified before the account exists)
- `POST /auth/register/request/` `{phone}` → 202 `{message}` (same answer whether or not the number is registered).
- `POST /auth/register/verify/` `{phone, code, name, date_of_birth, gender?: male|female|other, permanent_address, email?, aadhar_number?, consents?:[{purpose, policy_version, granted}]}`
  → 201 same token body as login (`{access, refresh, token_type, expires_in, user}`); the person is signed in.
  409 `already_registered` (after a valid code) means "use login instead". 400 `validation_error` with field details.
  Rules as built: `phone` is digits only, 10–15 characters (so the same string must be used at login); `code` is 6 digits; `name` 2–100 characters; `date_of_birth` in the past; `permanent_address` required; `aadhar_number` optional, 12 digits (spaces are ignored); `consents` entries with `granted:false` are ignored (nothing is recorded); the role is always `citizen`.
  Format errors (400) do **not** use up the code, so the form can be corrected and resubmitted with the same code. A 400 `aadhar_number` "cannot be used" error is checked after the code is verified and **does** use it up: send the person back to request a new code.
  A number that already has an account still receives a (login) code from `register/request/`, so nobody waits for a message that never comes; they find out it is taken only at verify (409). The 202 message and timing are the same in every case.
  Same limits as login: 60 s resend cooldown (off in the dev server), 5 wrong tries per code.

### B2 Voice and legal assistant — now AVAILABLE
Citizens need `ai_processing` consent (403 `consent_required` otherwise); officers and magistrates do not. Allowed roles: citizen, head_constable, sub_inspector, sho, magistrate (not admin). Limited to 30 AI calls/hour per user. `503 assistant_unavailable` on the voice calls means fall back to the browser's own speech/typing.
- `POST /voice/transcribe/` multipart form: `audio` (file; `audio/webm`, `video/webm`, `audio/ogg`, `audio/mpeg`, `audio/wav`, `audio/mp4`, `audio/m4a`; codec parameters such as `audio/webm;codecs=opus` are fine; ≤ 10 MB), `language` (`en|hi|te`, default `en`) → `{text, language}`. Record short clips (a question or an answer), not whole sessions. Audio is sent to the speech vendor and never stored here.
- `POST /voice/speak/` JSON `{text (≤ 1000 chars), language (en|hi|te)}` → raw `audio/mpeg` bytes (`Cache-Control: no-store`); play with `new Audio(URL.createObjectURL(blob))`. Do not cache or persist it.
- `POST /legal-assistant/ask/` `{question (≤ 1000), language?: en|hi|te}` → `{answer, in_scope: true|false|null, disclaimer, sources: [], ai_available}`. Citizens get general procedure information; officers get procedure/practice help (the server picks by role). `sources` is always `[]`: show the answer as AI-generated general information with the `disclaimer` (already in the requested language), and do not add citations. `in_scope:false` means the question was not about law/procedure and `answer` is a fixed polite refusal; `ai_available:false` (HTTP 200, `in_scope:null`) means the AI is down and `answer` is a fixed "ask your police station" message. Answers that look like legal advice, promises or invented page references are replaced by a fixed "could not give a reliable answer" message.
- The dev server has **no AI or speech keys**, so right now it answers `ai_available:false` and the voice calls return 503 `assistant_unavailable`: build the fallbacks against that. Ask the backend session if you need canned answers for UI work.

### B3 Richer officer case detail — now AVAILABLE (extra keys on `GET /police/complaints/<id>/`; nothing existing was removed)
`incident_date, incident_time, urgency_score, priority ("high" ≥ 80, "medium" ≥ 50, else "low"), station:{name}|null, assigned_officer:{name,phone}|null, assessment:{ai_status, needs_review, review_reasons[], sections:{code:title}, confidence, reviewed_at|null}, accused:[{name,description,contact_info,statement}], witnesses:[{name,contact_info,statement}], evidence_files:[{file_id,filename,type,size_bytes,uploaded,scan_status}]`.

### B4 Officer stats — now AVAILABLE
`GET /police/stats/` (any officer, and magistrates) → `{total, high_urgency_open, awaiting_ai_review, unassigned, assigned_to_me, filed_last_7_days, by_status:{<every status>:count}}`. `by_status` always lists all eight statuses (zero-filled). Scoped to what the caller may see: a constable's numbers cover only their own cases. `high_urgency_open` = open cases with urgency ≥ 80; `unassigned` = pending/under_review with nobody assigned; `awaiting_ai_review` = flagged, unreviewed, not still pending.

Also added to every row of `GET /police/complaints/`: `priority` and `status_label`.

### B5 Reference data and citizen progress — now AVAILABLE
- `GET /stations/` → `[{station_id, name, code, district, state}]` (any signed-in user; active stations only).
- Citizen `complaints/mine/` rows now also carry `status_label`, `progress_percent`, `ai_status` (null if there is no assessment yet) and `created_at`; newest first. `complaints/<id>/` now also carries `status_label`, `progress_percent`, `ai_status`, `assessment.ai_status`, `timeline:[{status, label, at}]` (internal officer remarks are never included) and `evidence_files:[{file_id, filename, type, size_bytes, uploaded, scan_status}]` (the old `evidence` list is the legacy URL-only kind and will normally be empty).
  Progress map: pending 10, under_review 25, gd_recorded 30, assigned 40, awaiting_magistrate 50, under_investigation 60, fir_registered 80, resolved 100.

### B6 Complete OpenAPI — now AVAILABLE
- Live: `GET http://localhost:8001/api/schema/` (YAML) and Swagger UI at `/api/docs/`. A checked-in snapshot is at `docs/openapi.yaml` in the backend repo (a test fails if it drifts, so it is always current).
- All 58 `/api/v1` operations have typed request and response bodies, a `bearerAuth` security scheme (the login/registration routes carry no requirement), and the standard `ErrorEnvelope` for 400/401/403/404/409/429/503. Operation ids are readable and stable (`get_police_complaints_by_complaint_id`, `post_auth_register_verify`).
- Generate types with e.g. `npx openapi-typescript <schema> -o src/api/schema.d.ts`. The backend session could not run a TypeScript generator itself, so tell it if the generated output has problems.
- Some pass-through objects are loosely typed on purpose (`user` inside complaint detail is a plain object; `GET /me/export/` is a free-form object). This contract file remains the description of behaviour and rules; the schema is the description of shapes.
- Regenerate the snapshot after any API change: `python manage.py spectacular --file docs/openapi.yaml`.

### B7 Demo data command (backend side) 
`python manage.py seed_demo` creates a station, a citizen (two), HC, SI, SHO, magistrate, admin and the case types. Phones: citizen `9000000001`, `9000000002`; HC `9000000011`; SI `9000000012`; SHO `9000000013`; magistrate `9000000021`; admin `9000000031`. With `DEV_FIXED_OTP=123456` every one logs in with code `123456`.

### B9 AI consent on the preview — now AVAILABLE
`POST /ai/assessments/` answers 403 `consent_required` for a citizen without `ai_processing` consent (officers are not asked). Show the consent screen, then retry.

### Open decisions (the frontend should isolate these behind one module)
- Where the refresh token lives. Until decided: keep the access token in memory and the refresh token in `sessionStorage`, all inside a single `auth/tokenStore` module so it can switch to an HttpOnly cookie later (B8).

## Changelog (the backend session adds a line each time something lands)

- `available_transitions` no longer lists `assigned`, and the status endpoint refuses it: a case can only become assigned through `POST /police/complaints/assign/`, so it can never be "assigned" to nobody. (Found while checking the officer screen in a browser.)
- Filing a complaint without `station_id` is no longer possible to do silently: it auto-routes when there is one active station, otherwise 400 `details.station_id` (asked by the frontend).
- **B6 live**: complete, typed OpenAPI at `/api/schema/` and `docs/openapi.yaml` (see the B6 section).
- Evidence upload now accepts `video/webm`, `audio/webm` and `audio/ogg`, and ignores codec suffixes in `content_type` (asked for by the frontend).
- **B2 and B9 live** on the dev server: `POST /voice/transcribe/`, `POST /voice/speak/`, `POST /legal-assistant/ask/`; `POST /ai/assessments/` now needs citizen AI consent. No AI/speech keys on the dev server, so they answer "unavailable" there.
- **B1 live** on the dev server: `POST /auth/register/request/` and `POST /auth/register/verify/` (signs the new citizen in). Details in the B1 section.
- **B3, B4, B5 live** on the shared dev server: `GET /stations/`, citizen progress fields and timeline, `evidence_files` on the citizen detail, rich officer detail, `GET /police/stats/`, `priority`/`status_label` on officer list rows. Shapes are in the sections above.
- **B7 live**: `seed_demo` command and a shared dev server at `http://localhost:8001` with demo logins (see "Running the backend locally"). In dev with `DEV_FIXED_OTP` the login resend cooldown and rate limits are off.
- CORS now allows the `Idempotency-Key` header and exposes `X-Request-ID` / `Content-Disposition`; dev CORS allows ports 8080, 3000, 5173, 4173.
