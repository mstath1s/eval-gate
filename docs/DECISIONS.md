# Decisions behind eval-gate

Short records of the choices that are not obvious from the code. Each one names the alternative
that was rejected, so a reviewer can argue with the choice instead of guessing at it.

## 1. A gate, not a dashboard

**Decision.** The primary output is a pass/fail verdict and an exit code.
**Rejected.** A dashboard that plots pass rate over time.
**Why.** A dashboard is read after the release. The failure this tool exists to prevent — a prompt
change that quietly breaks 8% of cases — happens before it. The verdict has to be in the pipeline,
where it can stop the merge. Plots can be added later; a gate that nobody wired into CI is the same
as no gate.

## 2. Suites and gates are JSON files, not code or YAML

**Decision.** `suites/*.json` and `gates/*.json`.
**Rejected.** Python test files; YAML.
**Why.** A suite is data: cases, expectations, thresholds. Keeping it data means a support lead can
propose a case without touching the package, and the diff of a threshold change is reviewable on
its own. YAML was rejected because the repository has no dependencies and `json` is in the standard
library — the whole tool installs and runs with nothing but Python.

## 3. Deterministic graders first, an LLM judge second

**Decision.** Every check defaults to a string, regex or JSON assertion. `llm_judge` must be asked
for explicitly, with a rubric and a minimum score.
**Why.** Deterministic checks are cheap, reproducible, and explainable in a PR comment. A judge is
useful exactly where criteria are judgemental ("is this explanation actually correct?"), and
dangerous everywhere else: it costs money, drifts with the judge model, and can be argued with.
Keeping the judge opt-in keeps its cost visible and its influence bounded.

## 4. Fail closed on missing cases and unknown prices

**Decision.** A run that produces fewer results than the suite has cases fails the gate. A model
with no entry in `pricing.json` makes the cost unknown, and unknown cost fails a cost threshold.
**Rejected.** Treating a missing result as skipped, and an unknown price as zero.
**Why.** Both shortcuts make a broken run look green — the failure mode this tool is built to
prevent. `0.0` for an unpriced model is the worst of the two: it turns "we have no idea what this
costs" into "this is free", in a report that otherwise looks authoritative.

## 5. The offline fixtures are deliberately imperfect

**Decision.** Two of the twelve scripted triage answers are wrong on purpose.
**Why.** A fixture set that always passes proves the happy path and nothing else. With two known
failures, the offline demo exercises the interesting half: the gate fails, the report names the
cases, the exit code is 1. The generator (`scripts/make_offline_fixtures.py`) documents which two
and why, so nobody mistakes the fixtures for model results.

## 6. Cost and latency are first-class, not reporting extras

**Decision.** Every result carries tokens, latency and cost; the gate has thresholds for all three.
**Why.** A quality gate with no cost ceiling produces a model that is correct and unaffordable. The
three move together — a prompt change that adds 400 tokens of instructions may improve the pass
rate and double the bill — so the decision has to see them at once.

## 7. Where this tool is the wrong answer

**Decision.** This is for a feature with a defined task and a way to check an answer.
**Why.** If the task has no checkable output, or the cases cannot be written down, a gate will
manufacture false confidence: it will pass a suite that never tested the thing that breaks. The
honest alternative is human review on a sample, and saying so.

## Known limitations

- One provider implementation (Mistral). The interface is small on purpose; a second adapter is
  the next change.
- The judge is uncalibrated against human labels. A judge failure is a prompt to look, not proof.
- No prompt or suite hashing yet, so two reports are not provably comparable.
- Concurrency is a fixed worker count. No token-bucket limiter, no queueing on `429` beyond one
  retry.
- The Gitea workflow in `.gitea/workflows/ci.yml` targets a self-hosted runner; if no runner is
  registered, it queues and never runs — check `actions/tasks` before believing a green badge.
