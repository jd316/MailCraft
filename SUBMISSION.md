# Submission — MailCraft (AI Engineer Candidate Assessment)

This file is the reviewer's entry point. Every assessment requirement is
mapped to a concrete artifact below.

## One-minute verification

```bash
make install-dev      # install deps
make test             # runs 157 tests in ~9s (no API key needed — tests use mock)
```

## To run the server or evaluation (requires AWS credentials)

```bash
cp .env.example .env
# Edit .env → configure LLM_PROVIDER and credentials (see .env.example)
make dev              # serves the UI at http://localhost:8000
make eval             # runs 10-scenario × 2-strategy evaluation
```

Tests use a mock adapter for speed and CI; the **server, UI, and eval
harness use real LLM APIs** (Bedrock for generation, Gemini for judging).

## Assessment requirement → where it lives

### §1 — The Assistant

| Requirement | Artifact |
|---|---|
| Takes Intent, Key Facts, Tone as inputs | `app/backend/core/schemas.py::GenerateRequest`, UI at `app/frontend/` |
| Produces a professional email | `POST /v1/generate` → `app/backend/services/generation.py` |
| Uses an LLM | AWS Bedrock (Mistral) at `app/backend/llm/bedrock_adapter.py`, Gemini judge at `app/backend/llm/gemini_adapter.py` |
| Advanced prompting technique **used** | `prompts/few_shot/advanced_v1.md` (role + decomposition + few-shot + self-rubric) |
| Advanced prompting technique **documented** | `docs/FINAL_REPORT.md §2`, `prompts/README.md` |

### §2 — Evaluation Strategy

| Requirement | Artifact |
|---|---|
| 10 unique input scenarios (Intent, Facts, Tone) | `eval/scenarios/default_10.json` |
| Human Reference Email for each scenario | `eval/references/default_10.json` |
| 3 custom metrics defined & implemented | `app/backend/evaluation/metrics.py`; documented in `docs/FINAL_REPORT.md §3` |
| Automated techniques (Python + LLM-as-Judge) | Metric 1 = Python rules; Metric 2 = LLM-judge; Metric 3 = hybrid |

### §2.C — Evaluation Report (CSV / JSON)

| Required content | File / location |
|---|---|
| Definition + Logic for each of the 3 metrics | `latest.json` → `metric_definitions`, also `docs/FINAL_REPORT.md §3` |
| Raw scores for all 10 scenarios × all 3 metrics | `eval/reports/committed/latest.csv` (20 rows = 10 scenarios × 2 configs) |
| Overall average score | `latest.json` → `average_scores`, `docs/FINAL_REPORT.md §4.3` |

### §3 — Model/Strategy Comparison and Analysis

| Requirement | Artifact |
|---|---|
| Run same 10 scenarios with same scoring on a second strategy | `baseline_v1` vs `advanced_v1` (same model, Mistral Large 3) — `eval/reports/committed/latest.{csv,json}` |
| Supplementary model comparison | Mistral Large 3 vs Mistral Small (same prompt) — `eval/reports/committed/model_comparison.{csv,json}` |
| Cross-model judge | Gemini 3.1 Pro (avoids self-evaluation bias) |
| *"Which strategy performed better?"* | `docs/FINAL_REPORT.md §5.1` |
| *"Biggest failure mode of the lower-performing strategy?"* | `docs/FINAL_REPORT.md §5.2` |
| *"Which do you recommend for production and why?"* | `docs/FINAL_REPORT.md §5.3` |

### Deliverables §1 — Code Repository

| Required | Artifact |
|---|---|
| GitHub-style repo with all code | this repository; structure documented in `README.md` |
| README explaining how to set up and execute | `README.md` (setup, test, run, eval, docker, audit targets) |

### Deliverables §2 — Final Report (PDF/Google Doc)

**Submitted as `docs/FINAL_REPORT.md`** — self-contained, no repo
navigation required. Convert to PDF with `make report` (requires `pandoc`).

| Section of the final report | Report §  |
|---|---|
| Prompt Template used (full text embedded) | §2.1 |
| Baseline prompt (for comparison) | §2.2 |
| Definitions and Logic for 3 Custom Metrics | §3 |
| Raw Evaluation Data (all 20 rows inline) | §4.2 |
| Comparative Analysis summary (~1 page) | §5 |

## Committed submission artifacts

```
docs/
  FINAL_REPORT.md        ← single self-contained report (PDF-ready)
  openapi.json              ← generated API spec

prompts/
  base/baseline_v1.md        ← baseline prompt
  few_shot/advanced_v1.md    ← the advanced prompting technique

eval/
  scenarios/default_10.json  ← 10 scenarios
  references/default_10.json ← 10 human reference emails
  reports/committed/
    latest.csv               ← prompt comparison raw scores (20 rows)
    latest.json              ← prompt comparison full structured output
    model_comparison.csv     ← model comparison raw scores (20 rows)
    model_comparison.json    ← model comparison full structured output
```

## Numbers at a glance

**Primary comparison — prompt strategy** (`eval/reports/committed/latest.json`):

| Metric | baseline_v1 | advanced_v1 | Δ |
|---|---:|---:|---:|
| `fact_inclusion` | 0.9750 | 0.9750 | 0.0000 |
| `tone_alignment` | 0.9750 | **1.0000** | +0.0250 |
| `professional_quality` | 0.8850 | **0.9760** | +0.0910 |
| **weighted_total** | 0.9480 | **0.9816** | **+0.0336** |

**Winner:** advanced_v1 — +9.1 pp on professional quality.
**Failure mode of baseline:** missing structural polish (no self-rubric,
no decomposition, no few-shot anchoring).
**Recommendation:** deploy advanced_v1 on Mistral Large 3.

**Supplementary — model size** (`eval/reports/committed/model_comparison.json`):
Mistral Large 3 (**0.987**) vs Mistral Small (**0.965**) — Large wins
on tone alignment (+15 pp on casual/assertive registers).

## Quality posture of the submitted code

- **157** automated tests, all passing (`make test`)
- **90 %** coverage
- **0** lint errors (`make lint`)
- Dockerfile + docker-compose + GitHub Actions CI
- Prometheus `/metrics`, `/readyz`, security headers, body-size middleware,
  per-route rate limits, secrets redaction, prompt-injection resistance
- Evaluation results generated with real LLM APIs (Bedrock + Gemini judge;
  mock used only for `make test`; eval CLI refuses mock for submission data)

## Generating the PDF

```bash
make report       # renders docs/FINAL_REPORT.md → docs/FINAL_REPORT.pdf
                  # (requires `pandoc`; see target for the exact command)
```
