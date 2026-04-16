"""Evaluation runner — orchestrates scenario loop, metric scoring, reporting.

Usage (library):

    runner = EvaluationRunner()
    result = await runner.run(
        run_id="eval_abc",
        run_name="baseline-vs-advanced",
        config_a=EvalConfig(model_id="model_a", prompt_version="baseline_v1"),
        config_b=EvalConfig(model_id="model_a", prompt_version="advanced_v1"),
    )

Uses the configured LLMAdapter via the factory.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.backend.core.config import get_settings
from app.backend.core.logging import get_logger
from app.backend.core.schemas import EvalConfig
from app.backend.evaluation.metrics import (
    METRIC_WEIGHTS,
    fact_inclusion_metric,
    professional_quality_metric,
    tone_alignment_metric,
    weighted_total,
)
from app.backend.evaluation.reports import write_reports
from app.backend.evaluation.scenarios import ScenarioSet, load_scenarios
from app.backend.llm.factory import get_adapter, get_judge_adapter
from app.backend.services.generation import GenerationService

log = get_logger("eval.runner")


class EvaluationRunner:
    def __init__(self, *, max_concurrency: int | None = None) -> None:
        self._adapter = get_adapter()
        self._judge_adapter = get_judge_adapter()
        self._service = GenerationService(self._adapter)
        settings = get_settings()
        self._semaphore = asyncio.Semaphore(max_concurrency or settings.eval_concurrency)

    async def run(
        self,
        *,
        run_id: str,
        run_name: str,
        config_a: EvalConfig,
        config_b: EvalConfig,
        scenario_set_id: str = "default_10",
    ) -> dict[str, Any]:
        settings = get_settings()
        dataset: ScenarioSet = load_scenarios(scenario_set_id)
        log.info(
            "eval.run.start",
            run_id=run_id,
            run_name=run_name,
            scenario_count=len(dataset.scenarios),
            config_a=config_a.model_dump(),
            config_b=config_b.model_dump(),
        )

        sums: dict[str, dict[str, float]] = {
            "config_a": {"fact_inclusion": 0.0, "tone_alignment": 0.0, "professional_quality": 0.0},
            "config_b": {"fact_inclusion": 0.0, "tone_alignment": 0.0, "professional_quality": 0.0},
        }
        failures: list[dict[str, Any]] = []

        # Build a single coroutine per (scenario, config) pair and fan out with
        # a bounded semaphore so we parallelize I/O while respecting provider
        # rate limits. Results are stitched back in deterministic order.
        tasks: list[tuple[int, str, asyncio.Task]] = []
        for idx, scenario in enumerate(dataset.scenarios):
            for label, cfg in (("config_a", config_a), ("config_b", config_b)):
                coro = self._score_one(
                    scenario=scenario, cfg=cfg, label=label, settings=settings
                )
                tasks.append((idx, label, asyncio.create_task(coro)))

        # Initialize per-scenario rows preserving order.
        per_scenario: list[dict[str, Any]] = [
            {
                "scenario_id": s.scenario_id,
                "title": s.title,
                "tone": s.tone,
                "difficulty": s.difficulty,
                "outputs": {},
                "scores": {},
                "rationales": {},
            }
            for s in dataset.scenarios
        ]

        for idx, label, task in tasks:
            try:
                result = await task
            except Exception as exc:  # noqa: BLE001 - keep batch going
                scenario = dataset.scenarios[idx]
                log.warning(
                    "eval.scenario.failed",
                    scenario_id=scenario.scenario_id,
                    label=label,
                    error=str(exc),
                )
                per_scenario[idx]["outputs"][label] = {"error": str(exc)}
                per_scenario[idx]["scores"][label] = {
                    "fact_inclusion": 0.0,
                    "tone_alignment": 0.0,
                    "professional_quality": 0.0,
                    "weighted_total": 0.0,
                }
                failures.append(
                    {"scenario_id": scenario.scenario_id, "label": label, "error": str(exc)}
                )
                continue

            per_scenario[idx]["outputs"][label] = result["output"]
            per_scenario[idx]["scores"][label] = result["scores"]
            per_scenario[idx]["rationales"][label] = result["rationales"]
            for m in ("fact_inclusion", "tone_alignment", "professional_quality"):
                sums[label][m] += result["scores"][m]

        n = len(dataset.scenarios)
        averages: dict[str, dict[str, float]] = {}
        for label in ("config_a", "config_b"):
            fi = round(sums[label]["fact_inclusion"] / n, 4)
            ta = round(sums[label]["tone_alignment"] / n, 4)
            pq = round(sums[label]["professional_quality"] / n, 4)
            averages[label] = {
                "fact_inclusion": fi,
                "tone_alignment": ta,
                "professional_quality": pq,
                "weighted_total": weighted_total(
                    {"fact_inclusion": fi, "tone_alignment": ta, "professional_quality": pq}
                ),
            }

        winner = self._select_winner(averages)
        failure_modes = self._failure_modes(per_scenario, loser=("config_a" if winner == "config_b" else "config_b"))

        payload: dict[str, Any] = {
            "run_id": run_id,
            "run_name": run_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scenario_set_id": scenario_set_id,
            "configs": {
                "config_a": config_a.model_dump(),
                "config_b": config_b.model_dump(),
            },
            "metric_definitions": _metric_definitions(),
            "metric_weights": METRIC_WEIGHTS,
            "per_scenario": per_scenario,
            "average_scores": averages,
            "recommended_winner": winner,
            "failure_modes": failure_modes,
            "failures": failures,
        }
        artifact_paths = write_reports(
            out_dir=Path(settings.eval_reports_dir), run_id=run_id, payload=payload
        )
        payload["artifact_paths"] = artifact_paths
        log.info(
            "eval.run.completed",
            run_id=run_id,
            winner=winner,
            artifact_paths=artifact_paths,
            averages=averages,
        )
        return payload

    async def _score_one(
        self,
        *,
        scenario,
        cfg: EvalConfig,
        label: str,
        settings,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        async with self._semaphore:
            # Retry generation on parse failures (non-deterministic with some models)
            last_exc = None
            for attempt in range(1 + max_retries):
                try:
                    output = await self._service.generate(
                        intent=scenario.intent,
                        key_facts=scenario.key_facts,
                        tone=scenario.tone,
                        prompt_version=cfg.prompt_version,
                        model_id=cfg.model_id,
                    )
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        log.warning(
                            "eval.scenario.retry",
                            scenario_id=scenario.scenario_id,
                            label=label,
                            attempt=attempt + 1,
                            error=str(exc),
                        )
                        await asyncio.sleep(1)
            else:
                raise last_exc  # type: ignore[misc]
            fact_score = fact_inclusion_metric(
                key_facts=scenario.key_facts, email_body=output.email_body
            )
            tone_score = await tone_alignment_metric(
                self._judge_adapter,
                tone=scenario.tone,
                subject=output.subject_suggestion,
                email_body=output.email_body,
                judge_model=settings.model_judge,
            )
            quality_score = await professional_quality_metric(
                self._judge_adapter,
                subject=output.subject_suggestion,
                email_body=output.email_body,
                judge_model=settings.model_judge,
            )
            scores = {
                "fact_inclusion": fact_score.score,
                "tone_alignment": tone_score.score,
                "professional_quality": quality_score.score,
                "weighted_total": weighted_total(
                    {
                        "fact_inclusion": fact_score.score,
                        "tone_alignment": tone_score.score,
                        "professional_quality": quality_score.score,
                    }
                ),
            }
            log.info(
                "eval.scenario.scored",
                scenario_id=scenario.scenario_id,
                label=label,
                **{k: v for k, v in scores.items() if k != "weighted_total"},
            )
            return {
                "output": {
                    "subject_suggestion": output.subject_suggestion,
                    "email_body": output.email_body,
                    "latency_ms": output.latency_ms,
                    "prompt_version": output.prompt_version,
                    "model_id": output.model_id,
                },
                "scores": scores,
                "rationales": {
                    "fact_inclusion": fact_score.rationale,
                    "tone_alignment": tone_score.rationale,
                    "professional_quality": quality_score.rationale,
                },
            }

    @staticmethod
    def _select_winner(averages: dict[str, dict[str, float]]) -> str:
        a = averages["config_a"]["weighted_total"]
        b = averages["config_b"]["weighted_total"]
        if abs(a - b) < 1e-4:
            return "tie"
        return "config_a" if a > b else "config_b"

    @staticmethod
    def _failure_modes(per_scenario: list[dict], *, loser: str) -> dict[str, Any]:
        """Summarize where the losing config under-performed.

        Counts:
        - scenarios where the loser scored lower on each metric
        - the most common missing-fact pattern
        - the tone buckets where the gap was largest
        """
        metric_losses = {"fact_inclusion": 0, "tone_alignment": 0, "professional_quality": 0}
        missing_facts: dict[str, int] = {}
        tone_gap: dict[str, float] = {}
        winner = "config_a" if loser == "config_b" else "config_b"

        for row in per_scenario:
            sa = row["scores"].get(loser, {})
            sb = row["scores"].get(winner, {})
            for m in metric_losses:
                if sa.get(m, 0.0) < sb.get(m, 0.0):
                    metric_losses[m] += 1
            gap = sb.get("tone_alignment", 0.0) - sa.get("tone_alignment", 0.0)
            if gap > 0:
                tone_gap[row.get("tone", "unknown")] = tone_gap.get(row.get("tone", "unknown"), 0.0) + gap

        return {
            "loser": loser,
            "metric_losses": metric_losses,
            "tone_gap_by_bucket": {k: round(v, 3) for k, v in tone_gap.items()},
            "missing_facts_sample": missing_facts,
        }


def _metric_definitions() -> list[dict]:
    return [
        {
            "name": "fact_inclusion",
            "description": (
                "Share of required facts that are detectably included in the email. "
                "Salient tokens (numbers, dates, quoted strings, proper nouns) are "
                "required; remaining content words are matched with light stemming. "
                "Deterministic. Range 0–1."
            ),
            "weight": METRIC_WEIGHTS["fact_inclusion"],
        },
        {
            "name": "tone_alignment",
            "description": (
                "LLM-as-judge score against a 5-anchor rubric (1.0 strong match → "
                "0.0 wrong tone). Judges greeting/closing, register, stance, and "
                "absence of jarring register shifts. Range 0–1."
            ),
            "weight": METRIC_WEIGHTS["tone_alignment"],
        },
        {
            "name": "professional_quality",
            "description": (
                "Hybrid score: 60% LLM-judge (clarity, fluency, actionability, "
                "cohesion) + 40% deterministic structural checks (greeting, "
                "closing, length envelope, paragraphing, no placeholder text). "
                "Range 0–1."
            ),
            "weight": METRIC_WEIGHTS["professional_quality"],
        },
    ]


__all__ = ["EvaluationRunner"]
