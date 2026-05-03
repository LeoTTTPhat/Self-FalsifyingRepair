# Self-Falsifying Repair (SFR) — Implementation Plan

A phased plan that takes the project from empty repository to NIER submission with results for the three pre-registered evaluation questions (held-out future-commit regression, per-step ablation, calibration of the differentiation score) plus the two open-question controls (mutation-testing comparison, agent-collusion sweep). Designed for a single PhD student with periodic advisor input. Total estimated effort: **~12 weeks of focused work**, with parallelizable evaluation runs.

The plan is intentionally falsifiable at every phase: each milestone has an acceptance criterion that, if it fails, surfaces a problem early rather than at submission time.

---

## Phase 0 — Project setup (Week 0, ~3 days)

**Goal:** a clean repository, reproducible environment, and a tiny end-to-end smoke test before any real engineering.

### Steps

1. **Repository skeleton.** Create a Python package `sfr/` with submodules `agent/`, `hypothesis/`, `counterfactuals/`, `differential/`, `adversary/`, `harness/`, `eval/`. Add `pyproject.toml`, lockfile, `tests/` mirror.
2. **Pinned environment.** Python 3.11, locked dependencies via `uv` or `poetry`. Pin both LLM client SDKs (patching model + adversary model). Pin the Defects4J version and the SWE-bench harness version.
3. **Reproducibility hygiene.** Single `make reproduce` target that, given a bug id, produces a deterministic output. Each run writes to `runs/<bug_id>/<timestamp>/` with `config.json`, `patch.diff`, `hypothesis.json`, `counterfactuals/{0..K-1}.py`, `differential.json`, `result.json`.
4. **Smoke test.** Run end-to-end on the CSV-quoted-comma example from the paper: produce a patch, articulate a hypothesis, synthesize counterfactuals, compute $\delta$. No quality target — just plumbing.

### Acceptance criterion
`make smoketest` produces a populated `runs/smoketest/` in under 90 seconds.

### Risks
- **Two-model orchestration.** Two distinct LLM clients with different rate limits and quirks add latent complexity. **Mitigation:** wrap both behind one `Model` interface from day one; never reach for SDK specifics outside that interface.

---

## Phase 1 — Hypothesis articulation (Week 1, ~5 working days)

**Goal:** a robust prompt-and-parse pipeline that, given a candidate patch, extracts a structured root-cause hypothesis from the agent.

### Steps

1. **Schema definition.** A hypothesis is the dataclass
   ```
   Hypothesis = (
     summary: str,                  # one-sentence claim
     predicate: Callable[Input, bool],
     rationale: str,
     confidence: float | None       # optional self-reported, recorded for calibration
   )
   ```
   The `predicate` is the load-bearing field: it must be an executable Python function over the same input type the failing test exercises.

2. **Prompt template.** A single, versioned template that instructs the agent to (a) restate the bug class in one sentence, (b) emit `def covers(input) -> bool:` characterizing inputs the bug should affect, (c) emit a 2–3 sentence rationale. The template is stored in `prompts/hypothesis_v1.md` and SHA-pinned in every run manifest.

3. **Parse + validate.** Robust extractor: regex to isolate the function block, AST validation that it parses, smoke execution on a synthetic input to confirm it doesn't raise on legal types. Failures tagged `hypothesis_parse_failed: true`; the patch goes through a single retry with the parse error appended to context.

4. **Predicate sandbox.** Each predicate runs in a subprocess with CPU and memory limits. We never trust agent-generated code in-process.

5. **Vacuous-hypothesis detector.** Run the predicate against the failing input *and* against 32 randomly-perturbed inputs. If it accepts only the failing input, flag as vacuous and force retry. (Concrete: predicates like `lambda x: x == failing_input` are detected.)

### File layout
```
sfr/hypothesis/
  __init__.py
  schema.py            # Hypothesis dataclass
  prompt.py            # versioned template loader
  extract.py           # regex + AST extractor
  sandbox.py           # subprocess + resource limits
  vacuous_check.py     # narrow-predicate detector
prompts/
  hypothesis_v1.md
```

### Acceptance criteria
- Extractor parses ≥ 95% of agent outputs cleanly on a 50-bug calibration set.
- Vacuous-hypothesis detector flags hand-constructed narrow predicates with 100% recall on a synthetic test set.
- Predicate sandbox rejects malicious payloads (file write, network call) on a curated safety test.

### Risks
- **Predicate-as-Python is too permissive.** Agents can write nontrivial Python in `covers`, including subtle bugs that make the predicate accept everything. **Mitigation:** the differential evaluator (Phase 3) catches this downstream — a permissive predicate produces counterfactuals that don't fail on the unpatched program, so $\delta = 0$, and the patch is rejected.

---

## Phase 2 — Counterfactual synthesis (Weeks 2–3, ~7 working days)

**Goal:** a synthesizer that, given a hypothesis $H$ and the existing test suite, produces $K$ counterfactual inputs satisfying $H$.predicate and not present in the suite.

### Steps

1. **Same-agent path.** Prompt the patching agent with $(H, P)$ and ask for $K_{\text{same}} = K/2$ inputs satisfying `H.covers`. Parse, validate, and run each candidate input through `H.covers` to confirm satisfaction.
2. **Adversary path.** Prompt a *different* model family with $(H, \text{spec only}, \text{not the patch})$ asking for $K_{\text{adv}} = K/2$ inputs. The adversary cannot see $P'$ to reduce confirmation bias.
3. **Distinctness check.** Reject inputs syntactically equal to or trivially equivalent to inputs already in the failing test or other counterfactuals. Implement at least string equality + light canonicalization (whitespace, casing on string inputs); document remaining gaps.
4. **Predicate gate.** Drop any candidate where `H.covers(candidate) == False`. The agent occasionally produces inputs that don't satisfy its own predicate; this filter is mandatory.
5. **Backfill on shortfall.** If after dropping we have $< K_{\min} = 4$ counterfactuals, re-prompt once with the surviving set in context. If we still have $< K_{\min}$, mark the hypothesis as un-falsifiable and reject the patch (a hypothesis that admits no counterfactuals is not testing anything).

### File layout
```
sfr/counterfactuals/
  __init__.py
  same_agent.py        # K/2 from patching agent
  adversary.py         # K/2 from independent model
  distinctness.py      # equality + canonicalization
  gate.py              # predicate-satisfaction filter
prompts/
  counterfactuals_same_v1.md
  counterfactuals_adv_v1.md
```

### Acceptance criteria
- On a 20-bug calibration set, ≥ 90% of accepted hypotheses produce $K \geq 4$ valid distinct counterfactuals on the first try.
- Predicate gate drop rate is logged per run (spurious-input rate is itself a metric of interest).
- Same-agent vs. adversary counterfactual distributions are visibly different on a hand-inspected sample (sanity check that the adversary isn't just repeating).

### Risks
- **Adversary cost.** Two model families × $K/2$ samples per accepted patch is expensive. **Mitigation:** cache adversary outputs keyed on `hash(hypothesis_text + model_id + seed)`; a re-run after harness fixes hits cache.
- **Distinctness check too weak.** Two inputs that are syntactically distinct but semantically equivalent both count toward $K$. **Mitigation:** for now, accept this as a known limitation; report on the rate at which $K$ effectively collapses (e.g., counterfactuals that all execute the same path through the unpatched program) as a diagnostic.

---

## Phase 3 — Differential evaluator (Week 4, ~5 working days)

**Goal:** compute $\delta$ and apply the acceptance gate.

### Steps

1. **Per-input runner.** Given $P$ (unpatched), $P'$ (patched), and $x_i$, run both programs on $x_i$ in sandboxed subprocesses with timeouts. Record `pass/fail` for each, and on fail, record the exception or assertion message.
2. **$\delta$ computation.**
   $$\delta = \frac{1}{K}\sum_{i=1}^K \mathbf{1}[P(x_i) \text{ fails}] \cdot \mathbf{1}[P'(x_i) \text{ passes}].$$
   Also record three diagnostic sub-rates: (a) $P$-fail rate (how often the input actually exercises the bug on unpatched code — this is the predicate's quality signal); (b) $P'$-pass rate (the symptom-level success rate of the patch on counterfactuals); (c) joint rate $\delta$ above.
3. **Acceptance gate.** Default $\delta^* = 0.5$. Patches with $\delta < \delta^*$ are rejected; the failing counterfactuals (those where $P'$ also fails) are appended to the agent's context for the next turn. The original failing test must also pass on $P'$.
4. **Audit log.** Every accepted patch's run record contains the full hypothesis, every counterfactual, every per-counterfactual outcome on both $P$ and $P'$. This is the single most important artifact for the rebuttal phase.

### File layout
```
sfr/differential/
  __init__.py
  runner.py            # sandboxed P(x) and P'(x)
  delta.py             # δ computation + sub-rates
  gate.py              # acceptance criterion
  audit.py             # structured logging
```

### Acceptance criteria
- Differential evaluator produces consistent $\delta$ values across two runs of the same fixed inputs (determinism check).
- On the smoke-test bug, the symptom-suppression patch from the paper's motivating example yields $\delta < 0.5$ and is rejected; a real fix yields $\delta \geq 0.75$ and is accepted.

### Risks
- **Flaky tests / nondeterministic programs.** A counterfactual might pass on $P'$ in one run and fail in another. **Mitigation:** run each counterfactual 3 times; require unanimous outcome to count, otherwise log as flaky and exclude from $\delta$. Track flake rate as a metric.

---

## Phase 4 — Agent harness wrapping (Week 5, ~5 working days)

**Goal:** wrap an off-the-shelf agent so that swapping `Base`, `Self-CF`, and `Self-CF+Adv` is a single CLI flag.

### Steps

1. **Agent abstraction.** Reuse the same shape as the upstream Trace-Grounded-Repair plan (Phase 3). One method `propose_patch(repo_state, failing_test) -> Patch`. Three implementations:
   - `BaseAgent` (unmodified loop, no SFR).
   - `SelfCFAgent` (after a candidate patch, runs Phases 1–3 with both counterfactual halves from the same model).
   - `SelfCFAdvAgent` (same, but half the counterfactuals from a separate adversary model).
2. **Loop control.** Up to 5 turns, capped at 10 minutes wall time per bug. On a failed gate, the rejected counterfactuals are appended to the agent's context for the next turn.
3. **Patch application.** Apply the agent's diff to the *original* tree, run failing test, then run the differential evaluator. Record the full transcript.
4. **Determinism scaffolding.** Log every prompt (hashed against the SHA-pinned template), every model call, every parsed artifact. Reproducibility is non-negotiable.

### Acceptance criterion
On a 5-bug subset, `sfr-run --mode {base,selfcf,selfcfadv} --bug X` produces identical schemas across the three modes; only the post-patch records differ.

### Risks
- **Agent loops that ignore counterfactuals on retry.** The whole point of feeding back failing counterfactuals is to drive the next attempt. If the agent ignores them, retries are wasted compute. **Mitigation:** measure the rate at which retried patches are syntactically distinct from previous attempts; if low, iterate on the retry prompt before scaling up.

---

## Phase 5 — Pilot study (Week 6, ~5 working days)

**Goal:** the 80-bug Defects4J pilot reported in the paper. Confirm the headline result is real *before* committing to the full evaluation.

### Steps

1. **Bug selection.** From Defects4J, restrict to single-test-failure cases for reproducibility. Sample 80 bugs uniformly across projects (at least 10 per project to limit project-specific bias).
2. **Pre-registration.** Commit the bug list, agent loop config, $\delta^* = 0.5$, $K = 8$, prompt template SHAs, and the future-commit regression test set per bug to a git tag *before* running. Reviewers will (rightly) ask if the 80 were cherry-picked.
3. **Run all three conditions.** Three seeds per bug per condition (720 runs). Use a job runner (`make pilot SEED=...`) and write to `runs/pilot/`.
4. **Compute three headline metrics.**
   - **Plausible rate.** Patches passing the original failing test.
   - **Correctness rate.** Patches additionally passing held-out tests drawn from the project's later commits *for the same function*.
   - **$\delta$ distribution.** For accepted patches, the empirical distribution over $\delta$.
5. **Symptom-suppression audit.** For every `Base`-plausible patch that fails at least one self-synthesized counterfactual, manually classify whether the patch is in fact a symptom suppression (special-case branch, broad except, etc.) or a real fix the counterfactual happened to misjudge. Report the precision of the gate.

### Acceptance criteria
- `Self-CF+Adv` correctness rate exceeds `Base` correctness rate by ≥ 8 absolute points with non-overlapping 95% CIs.
- `Self-CF+Adv` correctness rate exceeds `Self-CF` correctness rate by ≥ 3 points (otherwise the adversary is not worth its cost).
- Symptom-suppression audit precision ≥ 0.7 (flagged patches are real symptom-suppressions at least 70% of the time).

### Decision gate

```
After Phase 5 pilot:

Headline lift (Self-CF+Adv vs. Base, correctness)
├── ≥ +12 absolute points              → proceed confidently
├── +8 to +12, CIs disjoint            → proceed; consider tuning K, δ*
├── < +8 or CIs overlap                → STOP. Diagnose before scaling.
                                          Likely causes: predicate quality,
                                          counterfactual diversity, gate
                                          threshold.

Adversary contribution (Self-CF+Adv vs. Self-CF)
├── ≥ +3 points                        → keep adversary in full eval
└── < +3 points                        → drop adversary; report it as
                                          an ablation in the paper but
                                          don't pay the cost at scale

Symptom-suppression audit precision
├── ≥ 0.7                              → claim of "filters symptom
                                          suppression" is supported
└── < 0.7                              → soften the qualitative claim
                                          in the paper accordingly
```

### Risks
- **Defects4J ground-truth fragility.** The "developer fix" in the Defects4J record can itself be wrong or incomplete. **Mitigation:** the future-commit held-out test set is the primary correctness oracle; the developer-fix metric is secondary.
- **K = 8 is small.** With only 8 counterfactuals, $\delta$ has substantial sampling noise. **Mitigation:** we report both $\delta$ and bootstrap CIs over $\delta$; if noise is dominant, the natural follow-up is increase $K$ in the full eval.

---

## Phase 6 — Full evaluation (Weeks 7–10, ~3 weeks)

**Goal:** answer Q1, Q2, Q3 from §5 of the paper plus the two open-question controls.

### Q1: Held-out future-commit regression
- Replicate at scale on **SWE-bench Verified** (Python, real GitHub issues) and **BugsInPy** (Python, broader scope).
- For every accepted patch, run all tests added to the project in the subsequent 12 months (pulled directly from the project's git history).
- Patches that introduce regressions visible in the future test suite are counted as incorrect even if they passed the original failing test and the SFR gate.
- *Cost estimate:* ~$3–5k of LLM inference for the closed-model headline; budget for academic credits.

### Q2: Per-step ablation
- Three additional conditions:
  - **`Hyp-only`** — articulate the hypothesis but skip counterfactuals; gate is just whether the hypothesis is non-vacuous and the original test passes.
  - **`CF-only`** — synthesize $K$ random-but-valid counterfactuals (using a property-based test generator like Hypothesis or QuickCheck) without an explicit hypothesis; gate is $\delta \geq \delta^*$ on those.
  - **`Full`** — the full SFR protocol (Self-CF+Adv).
- Hypothesis: `CF-only` carries most of the signal in absolute terms, but `Hyp-only` makes counterfactual generation *targeted* rather than random — so `Full` substantially outperforms `CF-only`.

### Q3: Calibration of $\delta$
- For every accepted patch, plot $\delta$ vs. ground-truth correctness (from the future-commit regression).
- Compute Expected Calibration Error (ECE) and a reliability diagram.
- Goal: well-calibrated $\delta$ that lets agents quantify their own confidence. If $\delta$ is poorly calibrated, the gate threshold $\delta^*$ is doing the work and the per-patch confidence claim is weakened — we report this honestly.

### Open-question control 1: mutation-testing comparison
- For every accepted patch, run a mutation-testing tool on the patched program and ask: do the synthesized counterfactuals kill more mutants than a random equal-size input set drawn from a property-based generator?
- Hypothesis-targeted counterfactuals should kill more mutants in the bug class the hypothesis describes.

### Open-question control 2: agent-collusion sweep
- Vary the adversary model:
  - Same-family adversary (e.g., another instance of the patching model).
  - Different-family closed model.
  - Different-family open-weight model.
  - Non-LLM property-based test generator (Hypothesis library).
- Plot correctness lift vs. adversary heterogeneity. Hypothesis: heterogeneity matters; same-family adversary buys little.

### File layout
```
sfr/eval/
  benchmarks/
    defects4j.py
    swebench.py
    bugsinpy.py
  metrics.py           # plausible / correct / δ distributions / ECE
  ablations.py         # Hyp-only, CF-only, Full
  controls/
    mutation.py
    collusion.py
  reports/
    generate_tables.py
    generate_plots.py
```

### Acceptance criteria
- Each benchmark's headline result has `Self-CF+Adv` correctness > `Base` at $p < 0.05$ on a paired bootstrap test.
- Calibration plot is generated, ECE reported.
- Collusion sweep produces a clean monotonic plot or, if not, a documented and honestly-reported absence of trend.

### Risks
- **Future-commit oracle false-positives.** A patch may be correct yet break a future test that itself is wrong (e.g., a test that bakes in a specific implementation). **Mitigation:** when computing correctness, exclude future tests that the developer's reference fix also fails. Document this exclusion explicitly.
- **API cost overrun.** Two-model setup × 5 turns × thousands of bugs is expensive. **Mitigation:** budget cap per condition, cache aggressively, run open-weight ablations to keep closed-model spend on the headlines only.

---

## Phase 7 — Analysis & writing (Weeks 11–12, ~10 working days)

**Goal:** turn results into a NIER-quality 4-page paper.

### Steps

1. **Quantitative tables.** Auto-generate from `runs/`. No hand-edited numbers.
2. **Plots.** Three primary figures: (a) plausible vs. correct rates across conditions, (b) calibration / reliability diagram, (c) collusion-sweep curve. All script-generated.
3. **Worked examples.** Hand-pick three case studies for the paper:
   - A symptom-suppression patch the gate correctly rejects (the headline narrative).
   - A correct patch the gate correctly accepts at high $\delta$.
   - A correct patch the gate *incorrectly* rejects (honest reporting; characterize the failure mode).
4. **Threats section honesty.** Document every limitation discovered during execution.
5. **Independent re-coding.** A second annotator blind-re-codes the symptom-suppression audit from Phase 5 step 5. Report Cohen's kappa.
6. **Artifact.** Public anonymous repository with `make reproduce-paper` regenerating every table from cached `runs/`.

### Acceptance criteria
- Submission-ready PDF, 4 pages + 2 references, builds cleanly.
- Anonymous artifact repo with a clear README and a 30-minute reproducibility path on a single bug.

---

## Cross-cutting concerns

### Engineering hygiene
- One config file per experiment (`configs/pilot.yaml`, `configs/eval_swebench_full.yaml`). No CLI flags drifting between runs.
- Every run produces `manifest.json`: git SHA, patching model id, adversary model id, prompt template SHAs, $K$, $\delta^*$, dataset SHA. Without these, results are unreproducible.

### Determinism budget
- LLM stochasticity: control via temperature and seed; cache aggressively.
- Predicate execution: deterministic by sandbox construction; flaky tests handled per Phase 3.
- Differential evaluator: 3-run unanimity rule excludes flake.

### Safety
- Untrusted LLM-generated code (predicates *and* counterfactual inputs that can be programs in some benchmarks) runs in a `firejail` or `seccomp` sandbox. Never in-process.
- Resource caps per subprocess: 30s wall time, 1GB RSS, no network.

### Cost discipline
- Cache LLM completions keyed on `hash(prompt + model + temperature + seed)` for both patching and adversary models.
- Budget cap closed-model spend at the experiment-config level; refuse to launch if projected cost exceeds the cap.

### Failure handling
- Hypothesis parse fail → one retry; if still failing, treat as `Base` (no SFR gate) and log.
- Counterfactual shortfall ($K < K_{\min}$) → reject patch and force agent retry.
- Differential evaluator crash on a counterfactual → drop that counterfactual from $\delta$ (denominator shrinks); log.
- Whole bug crashes → re-run once; if it crashes again, drop with logged reason.

---

## Milestone calendar

| Week | Phase | Deliverable | Pass/fail |
|------|-------|-------------|-----------|
| 0 | Setup | Smoke test green | end-of-week |
| 1 | Hypothesis | Schema + parse + sandbox + vacuous detector on 50-bug calibration | end-of-week |
| 2–3 | Counterfactuals | Same-agent + adversary paths producing $K \geq 4$ on 90% of bugs | week 3 review |
| 4 | Differential evaluator | $\delta$ deterministic on smoke-test bug; gate behaves as expected | end-of-week |
| 5 | Harness | 3-mode CLI, identical schemas, retries feed counterfactuals back | end-of-week |
| 6 | Pilot | 80-bug Defects4J pilot, decision gate | **GO/NO-GO** |
| 7–8 | Eval Q1 | Future-commit regression on SWE-bench Verified + BugsInPy | week 8 review |
| 9 | Eval Q2 | Per-step ablation table (Hyp-only / CF-only / Full) | end-of-week |
| 10 | Eval Q3 + controls | Calibration, mutation comparison, collusion sweep | end-of-week |
| 11 | Analysis | Tables, plots, threats, audit re-coding | end-of-week |
| 12 | Writing | Submission-ready PDF + artifact | submission |

---

## What this plan deliberately does *not* do

- **No model fine-tuning.** The whole point of NIER is that SFR works with off-the-shelf agents. A fine-tuned-for-falsification ablation belongs in the follow-up full paper.
- **No formal verification.** The differential gate is empirical, not symbolic. A symbolic-execution-based version of the gate is a follow-up paper.
- **No multi-language pipeline.** Java (via Defects4J) and Python (via SWE-bench / BugsInPy) only. JavaScript / C / Rust are out of scope.
- **No production tooling.** Research artifact, not a deployable system. No IDE plugin, no CI integration, no service.
- **No deep counterfactual-quality theory.** We report empirical rates ($\delta$, $P$-fail rate, $P'$-pass rate) but do not formalize what makes a counterfactual "good." That's a separate paper.
- **No agent retraining loop.** We feed failing counterfactuals back as in-context retry signal, not as RL reward. RL on top of SFR is an obvious follow-up but is out of NIER scope.

The discipline of saying "no" to these is what keeps a 12-week project from becoming a 12-month one.

---

## Pilot decision tree (for quick reference)

The Phase 5 decision gate is the single most important checkpoint in the project. Restated as a tree:

```
Headline correctness lift (Self-CF+Adv vs. Base):
├── ≥ +12 points               → ✅ proceed to full eval confidently
├── +8 to +12, CIs disjoint    → ✅ proceed; consider tuning K, δ*
└── < +8 or CIs overlap        → ⛔ STOP. Diagnose before scaling.

If STOP, candidate diagnoses (in order of likelihood):
1. Predicate quality is poor → the hypothesis prompt is under-specified.
2. Counterfactuals are not diverse → distinctness check is too lax,
   or both halves are produced by similar models.
3. δ* threshold is wrong → check the δ distribution; is the gate
   firing on too few patches, or accepting clearly wrong ones?
4. Defects4J ground truth is too noisy for the lift to surface
   → switch the headline pilot to BugsInPy and re-run.

Adversary contribution (Self-CF+Adv vs. Self-CF):
├── ≥ +3 points                → keep adversary in full eval
└── < +3 points                → drop adversary; report as ablation only

Symptom-suppression audit precision:
├── ≥ 0.7                      → claim is supported as written
└── < 0.7                      → soften the qualitative claim
```

This decision tree, applied honestly, is what prevents three months of effort from arriving at a non-result that could have been called at week 6.
