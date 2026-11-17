# eval-gate

A release gate for LLM features: run a fixed suite of cases against a model, score every answer,
count the money and the latency, and **refuse the release** when a threshold is crossed.

The point is the exit code. A demo shows that a model can answer well once; a gate answers
*"is this model, on this prompt, at this price, still good enough to ship today?"* — and a CI job
can read the answer without a human in the loop.

```
$ python -m evalgate run --suite suites/support-triage.json --offline --gate gates/default.json
...
**GATE: FAIL**

| check | result | detail |
| --- | --- | --- |
| all_cases_ran | pass | 12/12 cases produced a result |
| error_rate | pass | 0 error(s) of 12, limit 0% |
| pass_rate | **fail** | 10/12 passed (83.3%), need 90% |
| grader:json_keys | pass | 0 failure(s), limit 0 |
| p95_latency_ms | pass | 12 ms, limit 8000 ms |
| cost_usd | pass | $0.000311, limit $0.050000 |
```

Exit codes: `0` gate passed · `1` gate failed · `2` the configuration is wrong.

## What it does

- **Suites are JSON files** with cases, a system prompt, and per-case checks. A suite is a
  reviewable artifact, not a notebook cell.
- **Graders are explicit and named:** `exact_match`, `contains_all`, `must_not_contain`, `regex`,
  `json_keys` (schema, optional type check), `json_value`. Deterministic by default.
- **`llm_judge` is opt-in per case**, takes a rubric and a minimum score, and its own token cost is
  tracked separately in the report.
- **Cost is computed from a pricing table with a retrieval date**, not from memory. A model that is
  missing from `pricing.json` makes the cost *unknown*, and an unknown cost fails a cost threshold
  instead of passing silently as zero.
- **The gate is a small JSON file** (`gates/default.json`): minimum pass rate, maximum error rate,
  p95 latency, total cost, per-grader failure limits, and whether every case must produce a result.
  A typo in a gate key is an error, not a silent default.
- **Two outputs per run:** JSON for the machine, Markdown for the pull request.

## Quickstart — no API key needed

The repository ships scripted answers so the harness can be exercised (and tested) offline.
Latency and cost in an `--offline` run are **simulated**: they measure the harness, not the model.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .                       # no runtime dependencies; the package uses the stdlib only

python -m evalgate suites              # bundled suites
python -m evalgate graders             # bundled graders
python -m evalgate run \
  --suite suites/support-triage.json \
  --offline --gate gates/default.json --out out
```

## Real run against the API

```bash
export MISTRAL_API_KEY=...             # never committed; .env is ignored
python -m evalgate run \
  --suite suites/support-triage.json \
  --model mistral-small-latest \
  --gate gates/default.json \
  --judge-model mistral-small-latest \
  --out out
```

`MISTRAL_API_KEY` is read from the environment only. The provider retries once on `429` and on
`5xx`, keeps `--max-workers` low by default to stay under a rate limit, and records attempts,
prompt tokens, completion tokens, latency and cost per case.

## Adding a case

```json
{
  "id": "triage-013",
  "input": "My invoice is in the wrong currency.",
  "checks": [
    { "grader": "json_keys", "keys": ["intent", "confidence", "needs_human"] },
    { "grader": "json_value", "key": "intent", "equals": "billing" }
  ]
}
```

Rules the loader enforces: a case needs `id`, `input` and at least one `checks` entry; an unknown
grader name is a load error, not a skipped check. A suite that silently runs fewer checks than it
says it does is worse than no suite.

## Status: what works, what does not

Working, covered by tests (`python -m unittest discover -s tests -t .` — 51 tests, no network):

- suite loading and validation, all six deterministic graders, `llm_judge` with cost tracking
- the gate: every check, fail-closed cost handling, per-grader limits
- end-to-end CLI runs, both `PASS` and `FAIL`, with reports written to disk
- an offline mode that fails loudly when a scripted answer is missing

Not built yet, in the order it matters:

1. **Baseline diffing** — store the previous run and report per-case regressions/newly-fixed, so a
   gate failure says *what changed* rather than *a number moved*.
2. **A second provider** — the interface exists (`Provider.complete`), only Mistral and the scripted
   provider implement it. A gate that cannot compare two models on the same suite is half a gate.
3. **Judge calibration** — `llm_judge` verdicts are not yet validated against human labels. Until
   they are, treat a judge failure as a suspicion, not a fact.
4. **Prompt/version stamping** — the report names the model but not the prompt hash or the suite
   hash, so two runs are not yet provably comparable.
5. **A minimal web view** — the Markdown report is enough for a reviewer, not enough for a team.

## Design notes

`docs/DECISIONS.md` records the seven decisions that shaped this: why a gate and not a dashboard,
why JSON suites, why fail-closed on cost and on missing cases, why the offline fixtures are
deliberately imperfect, and what would make this the wrong tool.

## Pricing provenance

`pricing.json` carries a `source` URL and a `retrieved` date (2026-11-17,
`docs.mistral.ai/inference/pricing`). Vendor prices change without notice. Re-check them before
quoting a cost figure from a report, and never let a stale table turn into a confident number.

## Licence

MIT.
