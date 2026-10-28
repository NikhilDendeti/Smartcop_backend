# AI operations

## What the AI does, and what it never does

| Piece | What it produces | Who decides |
|---|---|---|
| Classification | Suggested legal sections, urgency, a needs-review flag | An officer, through the AI review queue |
| Intake chat | Questions to the citizen and a pre-filled report | The citizen reviews and submits it |
| Status assistant | Plain answers about the status of the citizen's own complaint | Falls back to a fixed status message |
| Draft writer | An FIR or General Diary draft marked as AI-written | A commanding officer must approve it |
| Summariser | A summary where every fact cites a line of the case file | The officer reads the file |
| Triage | Suggested urgency and least-loaded constables (plain rules, no model) | The assigning officer |

No assistant changes a case's status, assigns work, files a complaint or sends a message. If the AI is
down, every one of them degrades to a manual path and says so.

Safeguards in the code: citizen text is wrapped as data and cannot close its own block; phone,
email and Aadhar numbers are masked before text leaves the server; outputs are checked against a
strict schema and the legal table; serious-offence keywords raise urgency and force review; and a
citizen's text is only analysed if they have consented (`ai_processing`).

## Choosing the provider

`GET/PATCH /api/v1/admin/ai/config/` (admin role):

```json
{"provider": "anthropic", "fallback_provider": "openai",
 "models_by_task": {"anthropic": {"classify": "claude-sonnet-5-5"}},
 "max_retries": 2, "timeout_seconds": 20, "monthly_budget_usd": "200.00", "kill_switch": false}
```

Models not named there use the defaults set by environment variables (`OPENAI_MODEL_CLASSIFY`,
`ANTHROPIC_MODEL_CLASSIFY`, and `..._INTAKE`, `_DRAFT`, `_SUMMARIZE`, `_ASSIST`). The defaults in the
code are placeholders. Check each vendor's current model list and pick deliberately: a stronger model for
`classify`, a cheaper one for `intake` and `assist`. Set `AI_PRICING_JSON` so cost and the budget work.

## Changing a model, a prompt or the provider safely

1. **Measure first.** Run the evaluation on the candidate:
   `python manage.py run_ai_eval --providers openai,anthropic --out report.json`
   (or the *AI evaluation* workflow). It reports category recall, serious-offence recall, silent
   downgrades, prompt-injection resilience, latency and cost per provider, and fails if a gate is missed.
   The gates: serious-case urgency recall >= 95%, silent downgrades 0, injection resilience 100%,
   category recall >= 80%, unavailable rate <= 5%.
2. **Canary.** Set `canary_provider` and a small `canary_percent` (for example 10). That share of
   requests tries the candidate first and falls back to the normal chain if it fails. Watch
   `/api/v1/admin/ai/usage/` and the officer override rate.
3. **Switch.** Raise the percentage, then change `provider`. Keep the old one as `fallback_provider`
   for a while.
4. **Roll back** by setting `canary_percent` to 0 or `provider` back; it takes effect immediately.

Prompts are versioned in the admin site (`PromptVersion`): create a new version and mark it active.
Each assessment records which prompt version produced it.

**The bundled evaluation cases are illustrative.** They were written without a legal reviewer and use
broad offence categories, not section numbers. Have a legal expert review and extend them before
treating the numbers as evidence. Include more Hindi, Telugu and other regional-language cases.

## The legal table

AI suggestions are validated against `LegalSection`. It ships with ten IPC sections and **no BNS
sections**, because the mapping must come from a legal reviewer. Until it is loaded, every result
for incidents on or after 1 July 2024 is flagged "needs review". Load a reviewed CSV with:

```bash
python manage.py load_legal_sections reviewed_sections.csv --dry-run   # check
python manage.py load_legal_sections reviewed_sections.csv
```

Leave `is_cognizable` blank where it is not confirmed; the system then keeps asking an officer.
The template is `ai/data/legal_sections_template.csv`.

## Day to day

- **Review queue**: officers work `GET /api/v1/police/ai-review-queue/`; each decision (accept, edit,
  reject) is stored and is the best material for improving the evaluation set.
- **Costs and health**: `/api/v1/admin/ai/usage/`, the `/metrics/` gauges, and the alerts in
  `deploy/prometheus-alerts.yml`.
- **Emergency stop**: `PATCH .../ai/config/ {"kill_switch": true}`. Complaints keep being filed and go to manual triage.
