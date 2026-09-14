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
| Reproducible | Cache keyed on model + prompt version + record, refusing hits whose request differs; seed sent; inter-run AC1 | `slr/adapters/llm.py`, `slr/eval/metrics.py` |
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
3. **Commit before every run.** The git SHA goes into the run artefact. Use
   `--require-clean` for any run you intend to report; without it the harness
   only warns. Untracked files under `runs/` do not count as dirty.
4. **Ground truth is never in a prompt.** `work.label_included` is written by
   `ingest.py` and read by `eval/metrics.py`. Nothing else may touch it —
   retrieval selects named columns so screening rows never carry it. Tests
   assert this; if one ever fails, every accuracy figure in the project is
   worthless.
5. **Results are reported per review, never pooled**, always with the
   inclusion rate beside them. Kusa et al. (2023) showed the field's default
   efficiency metric is not comparable across reviews of differing prevalence.
6. **A failed exit test cuts scope. It does not extend the week.**
7. **A negative result is a result.** Write it down the day it is observed,
   while the conditions are still fresh.

---

## Current state — week 8 of 15

Done: literature review, proposal (submitted), architecture, scope lock, the
walking skeleton, the week 8 evaluation harness, and the first baseline runs
on real SYNERGY data.

```
slr/
  config.py              YAML config + pydantic validation + config hashing
  db.py                  SQLite schema v3, FTS5 index, triggers
  services/
    ingest.py            SYNERGY loader; full reviews, upserts, NULLs kept NULL
    criteria.py          published eligibility criteria, pinned + hashed
    retrieve.py          random + BM25 ranking (baselines 1 & 2)
    screen.py            ask -> validate shape -> verify quote
    verify.py            THE span verifier. RQ1 lives here.
  adapters/llm.py        Mock + Gemini behind one Provider protocol,
                         response cache with request fingerprint, budget Meter
  eval/
    metrics.py           per-review metrics. Only module reading ground truth.
    agreement.py         Gwet's AC1/AC2, PABAK
    harness.py           CLI; writes runs/<ts>-<hash>/{config,resolved_config,
                         metrics,run,git_sha}
    report_tables.py     run directories -> reports/results.{csv,md}
prompts/screen_v1.txt    prompt template, versioned by filename
configs/smoke.yaml       Nelson_2002, 50 records, mock provider, free
configs/baseline_*.yaml  random and BM25 over Smid_2020 + Nelson_2002, free
configs/week08_gemini.yaml  Smid_2020 + Nelson_2002, gemini-2.5-flash-lite
tests/                   112 tests
reports/results.{csv,md} generated from runs/
```

**Verified on real data (commit 421e415, 15 September 2026):**

- SYNERGY v1.0 downloaded; ingest of Smid_2020 (2,627 / 27, 110 without
  abstract) and Nelson_2002 (366 / 80, 8 without abstract) matches the
  proposal exactly. Published criteria stored for both.
- Weeks 7–8 exit test, first half: `baseline_random`, `baseline_bm25` and
  `smoke` each run twice with `--require-clean`; all three pairs of
  `metrics.json` byte-identical. The second smoke run was served 50/50 from
  cache at $0.
- AC1 and quadratic AC2 reproduce the irrCAC worked example
  (`cac.raw4raters`: AC1 0.77544, AC2 0.914).

| Review | Prevalence | Random TNR@95 | BM25 TNR@95 | BM25 WSS@95 |
|---|---|---|---|---|
| Smid_2020 | 1.0% | 0.029 | 0.568 | 0.513 |
| Nelson_2002 | 21.9% | 0.066 | 0.080 | 0.024 |

**Observed 15 September 2026 (rule 7).** The lexical baseline does the
opposite of the inflation expected below: BM25 over the published criteria
saves most of the reading on Smid_2020 (1.0%) and almost none on Nelson_2002
(21.9%), where it barely beats random. Not yet explained. One hypothesis to
check, not a conclusion: Nelson_2002's candidate set was retrieved for a
single topic (HRT), so the criteria vocabulary is shared by nearly every
record and cannot separate them, whereas Smid_2020's candidates are lexically
diverse. Random is one seed; do not read its two values as different.

**Not yet done:**

- Never run against the real Gemini API. There is no `.env` and no key yet.
  `google-genai` is pinned at 0.3.0 (December 2024) and is untested against
  `gemini-2.5-flash-lite`; its usage metadata has no `thoughts_token_count`.
  If the first call fails on config or schema, upgrading the pin is a
  deliberate change to write down, not a silent one.
- Only Smid_2020 and Nelson_2002 are ingested. The other four load with the
  same command once added to a config.
- Ethics application for the usability study — not submitted. This is the only
  item whose timing is outside the author's control. It gates week 13. (The
  proposal, section 8.2, says approval is obtained in week 7.)

---

## Next: finish week 8 — first model recall figures

Exit test: *a stored configuration reproduces an identical metrics file, and a
first recall figure exists on two reviews.* The first half passes on real data;
the second needs the Gemini run.

1. `copy .env.example .env`, check `git check-ignore -v .env`, add
   `GEMINI_API_KEY`. Confirm on the Gemini deprecations page that
   `gemini-2.5-flash-lite` is still served and the prices in
   `configs/week08_gemini.yaml` still hold.
2. `python -m slr.eval.harness --config configs/week08_gemini.yaml --require-clean`
   — 2,993 calls, about $0.40, ceiling $2. Run it a second time: it must be
   served from cache at $0 with an identical `metrics.json`.
3. `python -m slr.eval.report_tables`, commit runs and reports as `eval:`, tag
   `week-08`.

When the model numbers arrive, set them beside the baselines above. Khraisha
et al. (2024) predict model accuracy looks better on the high-prevalence
review; the baselines already show prevalence is not the only thing that
varies between these two.

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
subset of 12,598 records** (≈ $1.90 per pass at the prices assumed in the
proposal; ≈ $1.60 at Gemini 2.5 Flash-Lite's September 2026 prices).

| Spend | Est. |
|---|---|
| Development and debugging (weeks 7–9) | $3 |
| Three prompt variants over the subset | $6 |
| Five repeated runs, two reviews | $3 |
| Model tier comparison, one review | $9 |
| Final reported runs | $4 |
| Contingency | $15 |
| **Total** | **≈ $43** |

Spend to date: $0 (baselines and mock runs only).

Four rules that keep it there:

- Cache checked before every call, keyed on (model, prompt_version, review,
  work_id).
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
accuracy is known to inflate on balanced data. Radjenović_2013 is software
engineering; Smid_2020 reviews statistical methodology (SEM, Bayesian
estimation in small samples).

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
budget remains. `slr/config.py` rejects any review outside this set. Hall_2012
and Radjenović_2013 are both fault-prediction reviews and will share papers —
which is why records are keyed on (review, work_id).

---

## Decisions already made — don't relitigate without reason

**Verification is substring matching after normalisation, not fuzzy
matching.** Fuzzy matching would let a paraphrase pass, and paraphrase is
precisely the failure being guarded against. Normalisation folds only
transport artefacts: NFKC, curly quotes → straight, en/em dash → hyphen,
whitespace collapsed, case folded. A single changed word must fail. There is a
test asserting that. **Do not "improve" this into fuzzy matching.** The
minimum span length applies after punctuation is stripped too.

**An unverified span is not a prediction.** Its decision becomes `unverified`
and accuracy is scored over verified decisions only. Scoring referrals as
predictions would flatter the system. `recall_with_referrals` is reported
beside it: what a researcher following the workflow keeps, counting everything
sent to a human.

**The mock provider fabricates ~20% of the time on purpose**, so the
verification failure path is exercised on every test run rather than being
discovered in week 10.

**Cache key excludes the prompt text, but the cache checks it.** Keyed on
model + prompt_version + review + work_id. Each cached row stores a hash of the
full request (prompt, model, temperature, max tokens, seed); a hit whose
request differs raises `CacheMismatch` and aborts. A prompt changed without a
version bump is a bug in the experiment, and it is caught rather than silently
served stale.

**Eligibility criteria are SYNERGY's published text, pinned.** Fetched from
`asreview/synergy-dataset@ca8cb9e2:datasets.toml` and refused if the sha256
differs. Not committed — quoted from third-party papers — but stored in the
database at ingest and hashed into every metrics file. A review without stored
criteria falls back to a one-line draft marked `working-draft`, and report
tables flag it.

**SYNERGY records are read through `Dataset.labels` and `Dataset.to_dict`**,
not `to_frame` (which hides `openalex_id` in the index and drops the label of
any work missing from the release). The `synergy get` CLI is not used.

**Records are keyed on (review, work_id).** A label belongs to the review, not
to the paper.

**Ingest loads every review in full; `max_records` caps screening only.** A
capped ingest changes stored prevalence, and every metric inherits it.

**metrics.json is a pure function of config and corpus.** No timestamps,
latency, cache state or commit hash — those live in run.json. This is what
makes "a stored configuration reproduces an identical metrics file" testable.

**The model's decisions are compared with baselines as a ranking.** Verified
includes by confidence, then referrals, then verified excludes least confident
first; TNR@95% is computed on that ordering.

**Inter-run agreement treats unverified decisions as missing ratings**, not
as a third category.

**Default model is gemini-2.5-flash-lite.** gemini-2.0-flash was shut down on
1 June 2026. Check the deprecations page before any reported run.

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
python -m slr.services.ingest --config configs/baseline_random.yaml
python -m slr.eval.harness --config configs/baseline_random.yaml --require-clean
python -m slr.eval.harness --config configs/baseline_bm25.yaml --require-clean
python -m slr.eval.harness --config configs/smoke.yaml --require-clean
python -m slr.eval.harness --config configs/week08_gemini.yaml --require-clean
python -m slr.eval.report_tables --runs runs --out reports
```

The first ingest downloads SYNERGY v1.0 (≈ 450 MB) to
`~/.synergy_dataset_source` and the criteria file to `data/synergy/`.
`configs/smoke.yaml` uses `provider: mock` — free, no API key, no network.

A database created before schema v3 is refused; delete `data/slr.db` and
re-run ingest.

**This repository is public.** `.env` is gitignored; verify with
`git check-ignore -v .env` before adding a real key. A leaked key is scraped
within seconds and history rewriting does not un-leak it. Revoke first, clean
later. SYNERGY abstracts may not be republished as plain text:
`data/` and `responses.jsonl` stay out of git.

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
- Kusa et al. (2023), *Intelligent Systems with Applications* 18:200193 — WSS not comparable across reviews; use normalised form (TNR at recall)
- Zhang et al. (2023), *Journal of Informetrics* 17(1):101373 — future-work sentence classification; macro F1 90.73%, but problem class only 43.64%
- Hida et al. (2026), arXiv:2604.27006 — 47 pp accuracy spread between models (22 pp on their other SLR); inter-run Gwet AC2 0.55 (Gemini-2.5-Flash) to 1.0 at temperature zero; title+keywords without the abstract −5.55 pp
- Gwet (2014), *Handbook of Inter-Rater Reliability*, 4th ed. — AC1/AC2; worked example `cac.raw4raters` used in `tests/test_agreement.py`
- De Bruin et al. (2023) — SYNERGY dataset, 26 reviews, 169,288 records, 1.67% inclusion
