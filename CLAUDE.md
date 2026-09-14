# CLAUDE.md

Project context for Claude Code. This file is loaded automatically at the
start of every session in this repository — read it before doing anything.

---

## What this is

**Beyond Retrieval** — an LLM-supported dashboard for literature review and
research gap detection. MSE907 capstone, Master of Software Engineering
(Level 9). Pehesara Gunawardena, student 270684416.

Fifteen-week project, solo developer, **roughly twelve hours a week**. That
constraint drives almost every decision below. When in doubt, prefer the
smaller thing that can be measured over the larger thing that cannot.

Repository: https://github.com/KavinduPehesara/Beyond-Retrieval (public)

---

## The two research questions

Everything in this repository exists to answer one of these. If a proposed
feature serves neither, it does not get built.

**RQ1 — Trustworthiness.** Can an LLM-supported literature review tool produce
screening decisions that a researcher can independently verify and rely on?

Trust is four measurable properties, each enforced by a mechanism in code
rather than assessed after the fact:

| Property | Enforced by | Where |
|---|---|---|
| Verifiable | A response is rejected unless its quote is found verbatim in the source | `slr/services/verify.py` |
| Accurate | The harness measures every configuration against recorded human decisions | `slr/eval/metrics.py` |
| Reproducible | Cache keyed on model + prompt version + record; fixed seeds; repeated runs | `slr/adapters/llm.py` |
| Overridable | System proposes, reviewer disposes; overrides kept as labelled data | `human_decision` table |

**RQ2 — Fast, accurate knowledge discovery.** How much reviewing effort, time
and monetary cost does the system remove at a fixed level of recall, and can
it surface the research gaps authors state in their own papers?

---

## Seven rules. Do not break these without saying so out loud.

1. **Nothing is optimised before the evaluation harness exists.** Week 8 comes
   before week 9 for a reason. A faster retriever with no way to measure it is
   hours that cannot be reported.
2. **Every reported number comes from a run directory** containing its config
   and commit hash. If a figure exists only in a terminal or a notebook, it
   does not exist.
3. **Commit before every run.** The git SHA goes into the run artefact. The
   harness prints a warning when the tree is dirty — do not ignore it.
4. **Ground truth is never in a prompt.** `work.label_included` is written by
   `ingest.py` and read by `eval/metrics.py`. Nothing else may touch it. There
   is a test asserting this; if it ever fails, every accuracy figure in the
   project is worthless.
5. **Results are reported per review, never pooled**, always with the
   inclusion rate beside them. Kusa et al. (2023) showed the field's default
   efficiency metric is not comparable across reviews of differing prevalence.
6. **A failed exit test cuts scope. It does not extend the week.**
7. **A negative result is a result.** Write it down the day it is observed,
   while the conditions are still fresh.

---

## Current state — week 7 of 15

Done: literature review, proposal (submitted), architecture, scope lock, and
the walking skeleton below.

```
slr/
  config.py              YAML config + pydantic validation + config hashing
  db.py                  SQLite schema, FTS5 index, triggers
  services/
    ingest.py            SYNERGY loader (stratified, so low-prevalence
                         samples are not all negatives)
    retrieve.py          FTS5 lexical rank + seeded random  (baselines 1 & 2)
    screen.py            ask -> validate shape -> verify quote
    verify.py            THE span verifier. RQ1 lives here.
  adapters/llm.py        Mock + Gemini behind one Provider protocol,
                         response cache, budget Meter that aborts
  eval/
    metrics.py           per-review metrics. Only module reading ground truth.
    harness.py           CLI; writes runs/<ts>-<hash>/{config,metrics,git_sha}
prompts/screen_v1.txt    prompt template, versioned by filename
configs/smoke.yaml       50 records, mock provider, free
tests/                   38 tests, most on the verifier
```

**Verified working:** 38 tests pass; end-to-end run on a synthetic corpus
screened 50 records, 82% verification rate, fabricated spans correctly caught
as `not_found`; second run served 50/50 from cache at $0.0000.

**Not yet done:**

- Never run against real SYNERGY data (download not yet performed)
- Never run against the real Gemini API (mock provider only so far)
- `CRITERIA` in `ingest.py` holds *working* eligibility criteria. Replace with
  SYNERGY's published protocol text before any run that gets reported.
- Ethics application for the usability study — not submitted. This is the only
  item whose timing is outside the author's control. It gates week 13.

---

## Next: week 8 — the evaluation harness

Exit test: *a stored configuration reproduces an identical metrics file, and a
first recall figure exists on two reviews.*

Build, in this order:

1. **`slr/eval/metrics.py` additions** — TNR@95% recall (normalised WSS, the
   form Kusa et al. proved comparable across reviews), Gwet's AC2,
   prevalence-adjusted kappa. **AC2 has no scikit-learn implementation. Write
   it and unit-test it against a published worked example before trusting a
   single number it produces.**
2. **Baselines** — random ordering (done) and BM25 alone (done). Wire them
   into the harness as selectable strategies rather than hard-coded calls.
3. **`report_tables.py`** — reads run directories, emits the CSV/markdown
   tables that go straight into the final report. Writing this in week 8 saves
   a full day in week 15.
4. **First real numbers** — run over Smid_2020 (2,627 records, 1.0%) and
   Nelson_2002 (366 records, 21.9%). These two bracket the prevalence range.

**Expect Nelson_2002 to look far better than Smid_2020.** That gap is not a
bug — it is exactly the inflation Khraisha et al. (2024) described, observed
in your own data. Write it down the day you see it.

---

## The rest of the schedule

| Week | Deliverable | Exit test |
|---|---|---|
| 9 | SPECTER2 embeddings, FAISS flat index, rank fusion (RRF, k=60), MiniLM cross-encoder over top 200 only | Beats the lexical baseline on ≥3 reviews |
| 10 | 3 prompt variants, 5 repeated runs, 2 model tiers, full subset run | Every property in the RQ1 table has a number |
| 11 | Gap discovery + **go/no-go checkpoint** | 30 gap statements rated, precision recorded, decision minuted with supervisor |
| 12 | FastAPI endpoints + 5 core Streamlit panels | Someone other than the author completes a query unassisted |
| 13 | Usability evaluation, hardening, reproduction script | A fresh clone runs on a second machine |
| 14 | Code frozen, all configs and baselines run, ASReview baseline | Every figure traces to a run directory and commit hash |
| 15 | Report, packaging, submission | Submitted |

**The week 11 checkpoint is real, not decorative.** The supervisor raised that
gap finding is hard to build. If precision on thirty sampled gap statements is
unacceptable, redirect remaining effort to prior-art retrieval: a researcher
describes their intended work, the system returns prior art they should know
about. That variant has ground truth for free — hide a recent paper, run its
abstract as the query, check whether the system retrieves the works that paper
actually cited. Either outcome is reportable.

---

## Budget — USD 50 total, hard ceiling

One pass over the full 169,288-record SYNERGY benchmark costs ≈ $25. The
experimental design needs ≈ 20 passes. That is why the corpus is a **six-review
subset of 12,598 records** (≈ $1.90 per pass).

| Spend | Est. |
|---|---|
| Development and debugging (weeks 7–9) | $3 |
| Three prompt variants over the subset | $6 |
| Five repeated runs, two reviews | $3 |
| Model tier comparison, one review | $9 |
| Final reported runs | $4 |
| Contingency | $15 |
| **Total** | **≈ $43** |

Four rules that keep it there:

- Cache checked before every call, keyed on (model, prompt_version, work_id).
- Budget ceiling lives in config and **aborts** the run. It does not warn.
- Every run logs tokens and cost per record into SQLite.
- While debugging, `max_records: 50`. Only runs you intend to report touch the
  full subset.

The **only** experiment permitted to bypass the cache is the week 10
repeated-run measurement, which needs genuine re-sampling to quantify variance.

---

## Evaluation corpus — the six reviews

Chosen so inclusion rates span 0.8% to 21.9%. Deliberately varying prevalence
is a stronger test than a larger corpus that does not, because screening
accuracy is known to inflate on balanced data. Two are software engineering.

| Review | Domain | Records | Included |
|---|---|---|---|
| Radjenović_2013 | Software engineering | 5,935 | 48 (0.8%) |
| Smid_2020 | Computer science | 2,627 | 27 (1.0%) |
| van_der_Waal_2022 | Medicine | 1,970 | 33 (1.7%) |
| Menon_2022 | Medicine | 975 | 74 (7.6%) |
| van_der_Valk_2021 | Medicine, psychology | 725 | 89 (12.3%) |
| Nelson_2002 | Medicine | 366 | 80 (21.9%) |
| **Total** | | **12,598** | **351 (2.8%)** |

`Hall_2012` (8,793, software engineering) is held as a week-14 extension if
budget remains. `slr/config.py` rejects any review outside this set.

---

## Decisions already made — don't relitigate without reason

**Verification is substring matching after normalisation, not fuzzy
matching.** Fuzzy matching would let a paraphrase pass, and paraphrase is
precisely the failure being guarded against. Normalisation folds only
transport artefacts: NFKC, curly quotes → straight, en/em dash → hyphen,
whitespace collapsed, case folded. A single changed word must fail. There is a
test asserting that. **Do not "improve" this into fuzzy matching.**

**An unverified span is not a prediction.** Its decision becomes `unverified`
and metrics score accuracy over verified decisions only. Scoring referrals as
predictions would flatter the system.

**The mock provider fabricates ~20% of the time on purpose**, so the
verification failure path is exercised on every test run rather than being
discovered in week 10.

**Cache key excludes the prompt text.** Keyed on model + prompt_version +
work_id. If the prompt changes without its version changing, that is a bug in
the experiment; a cache absorbing it silently would hide the bug.

**ASReview is run as an external tool**, not reimplemented. Removes an
implementation risk and a claim that would otherwise need defending.

**Flat FAISS index, not IVF.** 12,598 records is far too small for an
approximate index to be worth the accuracy loss.

**Rerank top 200 only.** Reranking everything is slow and pointless.

**RRF constant k=60, untuned.** No budget to justify a tuned value.

---

## Running it

```bash
.venv\Scripts\activate
pytest -q
python -m slr.services.ingest --config configs/smoke.yaml
python -m slr.eval.harness --config configs/smoke.yaml
```

`configs/smoke.yaml` uses `provider: mock` — free, no API key, no network.
Switch to `provider: gemini` and put `GEMINI_API_KEY` in `.env` for real runs.

**This repository is public.** `.env` is gitignored; verify with
`git check-ignore -v .env` before adding a real key. A leaked key is scraped
within seconds and history rewriting does not un-leak it. Revoke first, clean
later.

---

## Commit conventions

```
feat:   new capability
fix:    corrected behaviour
eval:   experiment run, metrics, analysis
docs:   README, proposal, supervisor reports
chore:  dependencies, config, housekeeping
```

One branch (`main`). Tag each week: `git tag -a week-08 -m "..."`.

Commit messages say what changed and why. In week 15 you will be
reconstructing week 9 from this log, and it is the only record that is not
memory.

---

## Weekly supervisor report

Five lines, same five every week. The exit test *is* the report — it is a
factual claim that is either true or false.

| Line | Content |
|---|---|
| Exit test | Passed / failed, plus evidence: a number, a run directory, a commit |
| Numbers this week | Any new figure, with the review and inclusion rate it came from |
| Spend to date | Dollars, from the database |
| Blocked on | Anything needing a decision or an approval |
| Next week | The next exit test, restated |

---

## Key references

- Bolaños et al. (2024), *AI Review* 57(10):259 — 21 tools surveyed, only 4 open source, 0 of 34 features concern absence
- Khraisha et al. (2024), *Research Synthesis Methods* 15(4):616–626 — GPT-4 sensitivity 0.42 on balanced data
- Kusa et al. (2023), *Intelligent Systems with Applications* 18:200193 — WSS not comparable across reviews; use normalised form
- Zhang et al. (2023), *Journal of Informetrics* 17(1):101373 — future-work sentence classification; macro F1 90.73%, but problem class only 43.64%
- Hida et al. (2026), arXiv preprint — 47pp accuracy spread between models; inter-run agreement 0.55–1.00 at temperature zero; abstract-only ablation −5.55pp
- De Bruin et al. (2023) — SYNERGY dataset, 26 reviews, 169,288 records, 1.67% inclusion
