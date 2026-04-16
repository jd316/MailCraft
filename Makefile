SHELL := /bin/bash
PY ?= python3
PIP ?= $(PY) -m pip
UVICORN ?= $(PY) -m uvicorn
APP := app.backend.main:app

.PHONY: help install install-dev run dev test lint fmt typecheck eval clean-drafts audit docker docker-run report clean

help:
	@echo "Targets:"
	@echo "  install       install runtime deps"
	@echo "  install-dev   install runtime + dev deps"
	@echo "  run           run the API server (production-style, workers=2)"
	@echo "  dev           run the API server with autoreload"
	@echo "  test          run full pytest suite with coverage"
	@echo "  lint          run ruff lint"
	@echo "  fmt           run ruff format"
	@echo "  typecheck     run mypy on app/"
	@echo "  eval          run full evaluation harness (10 scenarios x 2 strategies)"
	@echo "  clean-drafts  delete drafts older than DRAFT_RETENTION_DAYS"
	@echo "  audit         run pip-audit + bandit security scans"
	@echo "  docker        build the Docker image"
	@echo "  docker-run    run via docker-compose"
	@echo "  report        render the final report to PDF (requires pandoc)"
	@echo "  clean         remove caches, build artifacts"

install:
	$(PIP) install -r requirements.txt

install-dev:
	$(PIP) install -r requirements-dev.txt

run:
	$(UVICORN) $(APP) --host 0.0.0.0 --port 8000 --workers 2

dev:
	$(UVICORN) $(APP) --host 0.0.0.0 --port 8000 --reload

test:
	$(PY) -m pytest --cov=app --cov-report=term --cov-report=xml -q

lint:
	$(PY) -m ruff check app tests scripts

fmt:
	$(PY) -m ruff format app tests scripts

typecheck:
	$(PY) -m mypy app

eval:
	$(PY) -m app.backend.evaluation.cli run --out eval/reports

clean-drafts:
	$(PY) -m app.backend.admin.cli clean-drafts

audit:
	$(PY) -m pip_audit --strict --desc || true
	$(PY) -m bandit -q -r app

docker:
	docker build -t email-generation-assistant:latest .

docker-run:
	docker compose up --build

report:
	@if ! command -v pandoc >/dev/null 2>&1; then \
		echo "pandoc is required: https://pandoc.org/installing.html"; \
		echo "Tip: 'sudo apt-get install pandoc texlive-xetex' on Debian/Ubuntu."; \
		exit 1; \
	fi
	pandoc docs/FINAL_REPORT.md \
		-o docs/FINAL_REPORT.pdf \
		--from=gfm \
		--pdf-engine=xelatex \
		-V geometry:margin=0.85in \
		-V mainfont="DejaVu Sans" \
		-V monofont="DejaVu Sans Mono" \
		--toc --toc-depth=2 \
		--metadata title="Email Generation Assistant — Final Report" \
		|| pandoc docs/FINAL_REPORT.md -o docs/FINAL_REPORT.pdf --from=gfm
	@echo "PDF written to docs/FINAL_REPORT.pdf"

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache __pycache__ **/__pycache__ build dist *.egg-info coverage.xml
