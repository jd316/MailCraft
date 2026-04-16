# MailCraft

> *Turn intent into inbox-ready emails, powered by LLM.*

A production-grade LLM-powered service that turns a structured brief —
**intent, key facts, tone** — into a polished, send-ready business email.
Built as a candidate assessment for the AI Engineer role.

---

## What's in here

- **Backend** — FastAPI + async SQLAlchemy + SQLite (Postgres-ready) with
  structured `structlog`, Prometheus metrics, security headers, body-size
  limits, per-route rate limits, liveness/readiness endpoints, and a
  startup-time configuration validator.
- **Frontend** — zero-build accessible SPA (HTML + ES modules + CSS).
- **LLM adapters** — AWS Bedrock (Mistral) for generation + Google Gemini
  for cross-model judging, with exponential-backoff retry. Optional
  `MODEL_FALLBACK` swaps to a backup model on upstream errors. A
  deterministic mock adapter exists for `make test` and CI only — the
  server and eval harness require real provider credentials.
- **Prompt registry** — two versioned strategies:
  `baseline_v1` (minimal role prompt) and `advanced_v1`
  (role + structured decomposition + few-shot + self-rubric), both stored
  as diff-friendly Markdown under `prompts/` (see `prompts/README.md`).
- **Evaluation harness** — 10 scenarios, 10 human references, 3 custom
  metrics, CSV + JSON export, winner selection, failure-mode analysis,
  bounded concurrency.
- **Tests** — **157** unit + integration tests, **90% coverage**.
  Covers rate limits, error envelopes, security headers, `/readyz`,
  `/metrics`, CLI, admin CLI, prompt-injection resistance, fallback model,
  body-size middleware, eval API end-to-end, draft lifecycle (generate →
  revisions list → delete), non-functional (timeout, retry, safe
  rendering), and 2 golden fixtures for scorer stability.
- **Ops** — Multi-stage Dockerfile (non-root user, healthcheck),
  docker-compose with persistent volumes, `make audit` for
  `pip-audit` + `bandit`.
- **Docs** — **final report** at `docs/FINAL_REPORT.md` (PDF at
  `docs/FINAL_REPORT.pdf`), prompts README, OpenAPI spec at
  `docs/openapi.json` and served at `/docs`.

---

## Quick start

### 1. Install

Requires **Python 3.10+**. From the repo root:

```bash
make install-dev         # or: pip install -r requirements-dev.txt
cp .env.example .env
```

**Configure your LLM provider** (required for generation and evaluation):

```bash
# Edit .env — see .env.example for provider options (Bedrock, Gemini)
```

The server, the UI, and the evaluation harness use real LLM APIs via
the configured provider. Tests (`make test`) run without credentials —
they use a test-only mock adapter.

### 2. Run

```bash
make dev                 # reload server on http://localhost:8000
# or:  make run          # production-style, 2 workers
```

Open **http://localhost:8000** for the UI and **/docs** for OpenAPI.

### 3. Test

```bash
make test                # 157 passing tests, 90% coverage
make lint                # ruff
make typecheck           # mypy
make audit               # pip-audit + bandit
```

### 3b. Run in Docker

```bash
make docker              # build the image
make docker-run          # docker compose up (mounts ./data and ./eval/reports)
```

### 4. Run the full evaluation (10 scenarios × 2 strategies)

Requires a configured LLM provider in `.env` — the eval harness refuses to
run with the mock provider (mock-generated data is not suitable for submission).

```bash
make eval
# → writes eval/reports/eval_<id>_<timestamp>.{csv,json}
```

After running, copy the output to the committed snapshot:

```bash
cp eval/reports/eval_<id>.csv eval/reports/committed/latest.csv
cp eval/reports/eval_<id>.json eval/reports/committed/latest.json
```

---

## The Advanced Prompting Strategy

Strategy: **Expert role-playing + structured decomposition + few-shot
examples + self-rubric pass**, versioned as `advanced_v1`.

- **Role** — "Senior Executive Communications Specialist" stabilizes
  register and voice.
- **Method** — explicit Plan → Draft → Tone-check → Self-rubric → Emit
  decomposition, performed silently before the model emits the JSON.
- **Few-shot** — two high-quality examples (formal follow-up + urgent
  escalation) with the exact JSON output shape the API expects.
- **Self-rubric** — a 6-item checklist the model silently walks before
  emitting, explicitly including *"every key fact appears, undistorted"*.
- **Grounding** — the brief is framed as data; the prompt forbids
  inventing names/dates/prices/commitments that were not supplied.
- **Injection resistance** — explicit instruction to ignore embedded
  "ignore previous instructions" attacks.
- **Verifiability** — the model emits `fact_coverage[].evidence`
  substrings; the runtime cross-verifies every `included:true` claim
  against the actual email body and downgrades hallucinated claims.

Full prompt text: `prompts/few_shot/advanced_v1.md`.
Documented in depth in `docs/FINAL_REPORT.md §2`.

---

## The 3 Custom Metrics

| # | Metric | Range | Implementation | File |
|---|---|---|---|---|
| 1 | `fact_inclusion` | 0–1 | Deterministic, rule-based — salient-token extraction with stemmed word-boundary matching. Numbers, quoted strings, and proper-looking tokens are required; other content tokens are helpful. | `app/backend/evaluation/fact_matching.py` |
| 2 | `tone_alignment` | 0–1 | LLM-as-judge with a 5-anchor rubric (1.0 / 0.75 / 0.5 / 0.25 / 0.0) over four sub-criteria; temperature 0.0. | `app/backend/evaluation/metrics.py` |
| 3 | `professional_quality` | 0–1 | Hybrid — 60% LLM-judge over {clarity, fluency, actionability, cohesion} + 40% deterministic structural checks (greeting/closing present, length envelope, paragraphing, no `[placeholder]`). | `app/backend/evaluation/metrics.py` |

Weights: `0.45 / 0.25 / 0.30`.

Full definitions and per-scenario scores: `docs/FINAL_REPORT.md §3–4`
and `eval/reports/committed/latest.{csv,json}`.

---

## Comparative Analysis (assessment §3)

Two prompting strategies on the same 10-scenario dataset and the same
3-metric scorer:

| Config | fact_inclusion | tone_alignment | professional_quality | **weighted_total** |
|---|---:|---:|---:|---:|
| `baseline_v1` | 0.9750 | 0.9750 | 0.8850 | 0.9480 |
| `advanced_v1` | 0.9750 | **1.0000** | **0.9760** | **0.9815** |

**Winner — `advanced_v1`** (+3.35 pp). Biggest failure mode of the baseline:
lower professional quality due to missing structural polish (no self-rubric,
no decomposition). Full analysis in `docs/FINAL_REPORT.md §5`.

---

## API

OpenAPI contract generated at **`/docs`** when the server is running. Hand
specification lives at `docs/openapi.json`.

Core endpoints:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness probe |
| `GET` | `/readyz` | Readiness probe (DB + provider check) |
| `GET` | `/metrics` | Prometheus text exposition |
| `GET` | `/v1/meta` | Provider, models, prompt versions |
| `POST` | `/v1/generate` | Generate a draft |
| `POST` | `/v1/regenerate` | Regenerate with a revision instruction |
| `GET` | `/v1/drafts/{id}` | Fetch a persisted draft |
| `GET` | `/v1/drafts/{id}/revisions` | List the draft's revision history |
| `DELETE` | `/v1/drafts/{id}` | Delete a draft (cascades to revisions) |
| `POST` | `/v1/evaluations/run` | Start a 2-config evaluation run |
| `GET` | `/v1/evaluations/{id}` | Fetch evaluation status + artifacts |

Error envelope:

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "...", "request_id": "req_abc" } }
```

---

## Security & privacy

Security measures:

- Secrets loaded **from environment only**; never committed.
- Structured logs **redact** `api_key`, `authorization`,
  `password`, `token`, `secret`.
- Input validation via Pydantic with explicit max sizes and control-char
  stripping; `extra="forbid"` on request bodies.
- **Body-size middleware** rejects requests > `MAX_BODY_BYTES` (default
  32 KiB) before parsing.
- Model output is rendered strictly as **text** in the UI (never HTML).
- **Security headers** on every response: `X-Content-Type-Options`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, tight
  `Content-Security-Policy`, `Permissions-Policy`.
- Per-route **rate limits** (slowapi): 30/min on generation, 3/min on
  evaluation runs.
- CORS allow-list is explicit and defaults to localhost; wildcard is
  **refused** at startup when `APP_ENV=production`.
- Startup-time configuration validator refuses to boot in production if
  the API key is missing or CORS is wildcarded.
- Prompt-injection resistance is baked into the advanced prompt
  (`prompts/few_shot/advanced_v1.md`).
- `make audit` runs `pip-audit` + `bandit`.

---

## Project layout

```
.
├── app/
│   ├── backend/
│   │   ├── api/            # FastAPI routers + DI + rate limiting
│   │   ├── core/           # config, logging, schemas, errors,
│   │   │                   # middleware, telemetry (Prometheus)
│   │   ├── evaluation/     # metrics, runner, scenarios, reports, CLI
│   │   ├── llm/            # adapter interface + Bedrock + Gemini + mock
│   │   ├── persistence/    # SQLAlchemy models, repos, async engine
│   │   ├── prompts/        # registry + builder
│   │   ├── services/       # generation service
│   │   └── main.py         # FastAPI app factory
│   └── frontend/           # HTML + CSS + ES-module SPA (no build step)
├── prompts/                # versioned prompt strategies + README
│   ├── base/baseline_v1.md
│   └── few_shot/advanced_v1.md
├── eval/
│   ├── scenarios/default_10.json
│   ├── references/default_10.json
│   └── reports/committed/latest.{csv,json}
├── docs/                   # FINAL_REPORT.md, FINAL_REPORT.pdf, openapi.json
├── tests/                  # unit + integration (157 tests, 90% coverage)
├── Dockerfile              # multi-stage, non-root, healthcheck
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
└── Makefile
```

---

## Deliverables checklist (assessment §Deliverables)

- [x] Code repository with working prototype
- [x] README with setup + execution instructions (this file)
- [x] Documented advanced prompting technique
  (`prompts/few_shot/advanced_v1.md` + `docs/FINAL_REPORT.md §2`)
- [x] 10 unique input scenarios (`eval/scenarios/default_10.json`)
- [x] 10 human reference emails (`eval/references/default_10.json`)
- [x] 3 custom metrics defined & implemented
  (`app/backend/evaluation/metrics.py`)
- [x] Raw per-scenario scores, averages, and weighted totals
  (`eval/reports/committed/latest.{csv,json}`)
- [x] Comparison of two models/strategies on identical dataset + logic
- [x] Final report with definitions, logic, data, and recommendation
  (`docs/FINAL_REPORT.md`)

---

## License

MIT.
