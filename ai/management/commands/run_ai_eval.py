import json

from django.core.management.base import BaseCommand, CommandError

from ai.evals import runner


class Command(BaseCommand):
    help = (
        "Score the AI layer on a labelled set of incident reports, one provider at a time, and fail if "
        "it misses the quality gates. Makes real, billable model calls. Run it before changing a "
        "prompt or model, and to compare OpenAI and Claude on the same cases."
    )

    def add_arguments(self, parser):
        parser.add_argument("--providers", default="openai,anthropic", help="Comma-separated, e.g. openai,anthropic")
        parser.add_argument("--cases", help="Path to a JSONL case file (default: the bundled illustrative set)")
        parser.add_argument("--limit", type=int, help="Only run the first N cases")
        parser.add_argument("--out", help="Write the full report to this JSON file")
        parser.add_argument("--no-gate", action="store_true", help="Report only; do not fail on the quality gates")

    def handle(self, *args, providers, cases, limit, out, no_gate, **options):
        case_list = runner.load_cases(cases)[:limit] if limit else runner.load_cases(cases)
        report, problems = {}, []

        for provider in [name.strip() for name in providers.split(",") if name.strip()]:
            self.stdout.write(f"Running {len(case_list)} cases on {provider} ...")
            summary = runner.evaluate(provider, case_list)
            report[provider] = summary
            for problem in runner.failed_gates(summary):
                problems.append(f"{provider}: {problem}")

        self.print_table(report)
        if out:
            with open(out, "w", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2, ensure_ascii=False)
            self.stdout.write(f"Full report written to {out}")

        if problems and not no_gate:
            raise CommandError("Quality gates failed:\n  " + "\n  ".join(problems))
        self.stdout.write(self.style.SUCCESS("Done." if no_gate else "All quality gates passed."))

    def print_table(self, report):
        metrics = [
            "category_recall", "category_precision", "serious_urgency_recall", "serious_protected_rate",
            "false_downgrade_rate", "injection_resilience", "no_offence_handled", "unavailable_rate",
            "latency_ms_p50", "latency_ms_p95", "model_calls", "fallback_calls", "cost_usd",
        ]
        names = list(report)
        self.stdout.write(f"\n{'metric':28}" + "".join(f"{name:>14}" for name in names))
        for metric in metrics:
            self.stdout.write(f"{metric:28}" + "".join(f"{str(report[name][metric]):>14}" for name in names))
        for name in names:
            for failure in report[name]["failures"]:
                self.stdout.write(f"  [{name}] missed {failure['id']}: expected {failure['expected']}, "
                                  f"got {failure['predicted']}, urgency {failure['urgency']}")
        self.stdout.write("")
