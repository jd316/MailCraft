# Golden fixtures

Frozen input briefs and their expected metric scores, used to keep the
scoring logic deterministic across refactors (docs/07_TEST_PLAN.md §4
"Golden test strategy").

Each fixture file contains:

- `scenario` — the brief (intent, key_facts, tone)
- `email` — a frozen generated email body
- `expected` — the expected metric scores, with tolerance bands

`test_golden_fixtures.py` iterates the directory and asserts the scorers
still produce these numbers. When a scorer is intentionally changed, the
expected values MUST be refreshed in the same PR.
