"""CLI entry point for the evaluation harness.

Examples:

    python -m app.backend.evaluation.cli run \\
        --compare baseline_v1 advanced_v1 \\
        --model claude-sonnet-4-6 \\
        --out eval/reports

    python -m app.backend.evaluation.cli run \\
        --compare-models claude-haiku-4-5-20251001 claude-sonnet-4-6 \\
        --prompt advanced_v1 \\
        --out eval/reports
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from app.backend.core.config import get_settings
from app.backend.core.logging import configure_logging, get_logger
from app.backend.core.schemas import EvalConfig
from app.backend.evaluation.runner import EvaluationRunner

log = get_logger("eval.cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eval", description="MailCraft evaluator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Run the full 10-scenario evaluation")
    run.add_argument("--scenarios", default="default_10", help="Scenario set id")
    run.add_argument(
        "--compare",
        nargs=2,
        metavar=("PROMPT_A", "PROMPT_B"),
        help="Compare two prompt strategies on the same model",
    )
    run.add_argument(
        "--compare-models",
        nargs=2,
        metavar=("MODEL_A", "MODEL_B"),
        help="Compare two models on the same prompt strategy",
    )
    run.add_argument("--model", help="Model to use for --compare (defaults to MODEL_PRIMARY)")
    run.add_argument("--prompt", help="Prompt to use for --compare-models (default advanced_v1)")
    run.add_argument("--name", default="eval-run", help="Human-readable run name")
    run.add_argument("--out", default=None, help="Override reports output dir")

    return parser


async def _cmd_run(args: argparse.Namespace) -> int:
    if args.out:
        os.environ["EVAL_REPORTS_DIR"] = str(args.out)
        Path(args.out).mkdir(parents=True, exist_ok=True)
        get_settings.cache_clear()
    settings = get_settings()

    # Guard: refuse mock-generated eval results for real submissions.
    provider = settings.effective_provider
    if provider == "mock" and settings.app_env != "test":
        print(
            "ERROR: Evaluation is running with the mock provider.\n"
            "Mock-generated results are not suitable for submission.\n\n"
            "  Option 1: Set LLM_PROVIDER=bedrock (uses AWS credentials)\n"
            "  Option 2: Set ANTHROPIC_API_KEY in your .env file\n\n"
            "To force mock (testing only): set APP_ENV=test",
            file=sys.stderr,
        )
        return 1
    print(f"Provider: {provider}", file=sys.stderr)
    print(f"Model primary: {settings.model_primary}", file=sys.stderr)
    print(f"Model judge: {settings.model_judge}", file=sys.stderr)

    if args.compare and args.compare_models:
        print("Use either --compare OR --compare-models, not both.", file=sys.stderr)
        return 2
    if not args.compare and not args.compare_models:
        # Default: compare two models with the same advanced prompt (assessment §3).
        args.compare_models = [settings.model_primary, settings.model_secondary]

    if args.compare:
        model = args.model or settings.model_primary
        config_a = EvalConfig(model_id=model, prompt_version=args.compare[0], label="config_a")
        config_b = EvalConfig(model_id=model, prompt_version=args.compare[1], label="config_b")
    else:
        prompt = args.prompt or "advanced_v1"
        config_a = EvalConfig(model_id=args.compare_models[0], prompt_version=prompt, label="config_a")
        config_b = EvalConfig(model_id=args.compare_models[1], prompt_version=prompt, label="config_b")

    run_id = f"eval_{uuid.uuid4().hex[:12]}"
    runner = EvaluationRunner()
    payload = await runner.run(
        run_id=run_id,
        run_name=args.name,
        config_a=config_a,
        config_b=config_b,
        scenario_set_id=args.scenarios,
    )

    print(json.dumps({
        "run_id": payload["run_id"],
        "recommended_winner": payload["recommended_winner"],
        "averages": payload["average_scores"],
        "artifact_paths": payload["artifact_paths"],
    }, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "run":
        return asyncio.run(_cmd_run(args))
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
