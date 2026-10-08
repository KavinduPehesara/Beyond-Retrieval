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

## Current state — week 13 of 15

Done: literature review, proposal (submitted), architecture, scope lock, the
walking skeleton, the week 8 evaluation harness, the first baseline runs on
real SYNERGY data, the first model recall figures (local Ollama), week 9's
dense retrieval (SPECTER2 + FAISS, RRF fusion, cross-encoder rerank), week
10's prompt variants, model tier comparison, the overridable mechanism, and
genuine inter-run reproducibility, week 11's gap-discovery mechanism with 74
rated statements across all six reviews (87.8% precision) — go/no-go
decision not yet minuted with the supervisor — week 12's FastAPI
backend and 5 Streamlit panels, built and verified working end-to-end
against real data, but not yet run through its actual exit test (a second
person completing a query unassisted) — and week 13's hardening: the
fresh-clone exit test actually run (not assumed), a reproduction script,
the Gemini config fix, and week 14's ASReview baseline pulled forward on
two reviews. Weeks 8, 9 and 10 exit tests passed; weeks 11 and 12 are both
open pending two events outside code (a supervisor decision, a second
person at the keyboard); week 13 is open pending the ethics-gated half of
its own usability evaluation. Also done, outside the original schedule: a
structured data-extraction feature and report, added at the supervisor's
request (see 21 September note below).

```
slr/
  config.py              YAML config + pydantic validation + config hashing
  db.py                  SQLite schema v4, FTS5 index, triggers
  services/
    ingest.py            SYNERGY loader; full reviews, upserts, NULLs kept NULL
    criteria.py          published eligibility criteria, pinned + hashed
    retrieve.py          random + BM25 ranking (baselines 1 & 2), dispatches
                         dense/hybrid/rerank into dense_retrieve.py
    dense_retrieve.py    SPECTER2 + FAISS cosine search, RRF fusion (k=60),
                         cross-encoder rerank over the fused top 200
    screen.py            ask -> validate shape -> verify quote
    extract.py            same pattern, per field: study_design, sample_size,
                         country, key_finding. extraction's sibling to screening.
    gap.py                 same pattern, one field: does the abstract state a
                         research gap? extraction's sibling for RQ2.
    verify.py            THE span verifier. RQ1 lives here. Shared by all three.
    override.py           human_decision reads/writes. Blind to label_included,
                         same boundary screen.py keeps.
    extract_fulltext.py     5 fields that only exist in a paper's body:
                         primary_outcome, effect_size, statistical_methods,
                         sample_characteristics, limitations. Same ask ->
                         validate -> verify as everything else; the span is
                         checked against exactly the text the model was
                         shown, with table content stripped out so a cell
                         cannot be quoted as prose.
    discover.py             OpenAlex live search -> extract.py/gap.py, unchanged.
                         review="_discover", never written to `work` --
                         outside the evaluation corpus by construction.
  adapters/
    fulltext.py            Europe PMC: DOI -> open-access JATS XML -> sections,
                         tables, equations, figure captions. Tables and
                         equations are parsed, not inferred, so they are
                         exact. Reports WHY there is no full text --
                         paywalled and not-indexed are facts, not failures.
    llm.py                Mock + Gemini + Ollama behind one Provider protocol,
                         response cache with request fingerprint (now includes
                         response_schema), budget Meter
    embed.py              SPECTER2 via AutoAdapterModel + proximity adapter
    rerank.py              MiniLM cross-encoder (ms-marco-MiniLM-L-6-v2)
  eval/
    metrics.py           per-review metrics + override_accuracy (the one join
                         allowed to compare a human override with ground
                         truth). Only module reading ground truth.
    agreement.py         Gwet's AC1/AC2, PABAK
    harness.py           CLI; writes runs/<ts>-<hash>/{config,resolved_config,
                         metrics,run,git_sha}
    extract_harness.py   CLI; reads a screening run's verified-includes,
                         writes runs/<ts>-extract-<hash>/{...,extraction.jsonl}
    gap_harness.py         CLI; same source, writes runs/<ts>-gap-<hash>/{...,
                         gap_statements.jsonl}. Reuses ExtractConfig as-is.
    override_cli.py       records one human disposition against a run
    override_report.py   writes runs/<ts>-<hash>/overrides.json
    gap_report.py          writes runs/<ts>-gap-<hash>/gap_ratings.json
    gap_recall.py          blind-labelled recall estimate for gap discovery
    inter_run.py          genuine inter-run Gwet AC1 across repeated runs
    ablation.py            what each component buys. Reconstructs the
                         un-verified system from cached_response, so the
                         counterfactual is exact rather than estimated.
                         PolicyResult.comparable guards the one comparison
                         that is not like-for-like.
    ablation_harness.py    CLI -> runs/<ts>-ablation-<hash>/
    error_typology.py      why verification fails. echoed_criteria is the
                         category that matters: 97.8% of failures are the
                         model quoting the criteria, not inventing a quote.
    typology_harness.py    CLI -> runs/<ts>-typology-<hash>/, plus a seeded
                         blind rating sheet
    charts.py              one pure data function per dashboard chart. Lives
                         here, not in api/, because four of them read
                         label_included (recall curve, prevalence, scatter)
                         and rule 4 allows that only inside slr/eval.
    report_tables.py     run directories -> reports/results.{csv,md}
    asreview_baseline.py   exports one review to ASReview's own CSV shape
    asreview_report.py     turns a finished `asreview simulate` into the
                         same ranking_metrics() figure every other
                         strategy uses -- week 14, pulled forward
  api/
    app.py                 FastAPI routes -- reads a run directory or the
                         live tables, or calls a service function directly.
                         POST /query/screen is the one route that writes.
                         8 /charts/* routes wrap eval/charts.py.
    runs_index.py           "current" run per review per harness kind
    deps.py                 DB_PATH/RUNS_DIR/PROMPTS_DIR, get_conn
    schemas.py              pydantic request/response models
app/
  Home.py                 the front door: "What are you researching?" --
                         deliberately not the six-review table, which made
                         the tool demo as a report about six old reviews
  api_client.py            thin httpx wrapper, one function per route
  plots.py                 Altair builders, one per chart. Draws only --
                         every number comes from /charts/* via charts.py
  pages/1_Run_a_Review.py         THE PRODUCT. Live literature, the user's
                                 own criteria, screened + extracted +
                                 gap-checked. No reported figure: no ground
                                 truth exists for an ad-hoc topic.
  pages/2_Validation_Trust.py     the RQ1 table + corpus + trust charts
  pages/3_Validation_Screening.py rank + live-screen up to 15 -- the week 12
                                 query exit test runs here
  pages/4_Validation_Decisions.py
  pages/5_Validation_Extraction.py
  pages/6_Validation_Gaps.py
                         Every validation page carries a banner saying it is
                         evidence, not the tool. A test asserts all five do.
prompts/screen_v1.txt    prompt template, versioned by filename
prompts/screen_v2.txt    step-by-step + one-sentence reasoning (week 10, underperformed v1)
prompts/screen_v3.txt    terse, minimal rules (week 10, underperformed v1)
prompts/extract_v1.txt   extraction prompt: 4 fields, each with a quote or "not_stated"
prompts/gap_v1.txt       gap-discovery prompt: 1 field, "gap_stated" or "not_stated"
prompts/extract_fulltext_v1.txt  full-text prompt, 5 fields. Forbids quoting the
                         instructions -- directly informed by the 5 Oct typology
                         finding that 97.8% of screening failures were criteria echoes
configs/smoke.yaml       Nelson_2002, 50 records, mock provider, free
configs/baseline_*.yaml  random and BM25 over Smid_2020 + Nelson_2002, free
configs/week08_gemini.yaml  Smid_2020 + Nelson_2002, gemini-3.5-flash-lite (priced 2 Oct, not run)
configs/week08_ollama.yaml  same two reviews, local GPU via Ollama, qwen2.5:7b-instruct
configs/extract_demo*.yaml  verified-includes per review, local Ollama, $0
configs/valk2021_ollama.yaml  van_der_Valk_2021 screening, local Ollama, $0
configs/radjenovic2013_ollama.yaml  Radjenovic_2013 screening, local Ollama, $0
configs/week09_*.yaml    bm25/dense/hybrid/rerank across all 3 ingested reviews
configs/week10_prompt_v*_nelson.yaml  prompt variant comparison, Nelson_2002
configs/week10_model_qwen3_nelson.yaml  model tier 2, Nelson_2002
configs/week10_repeat_nelson.yaml  cache_enabled: false, 5x for inter-run AC1
configs/week10_full_subset.yaml  all 4 ingested reviews under one run_id
configs/gap_demo_*.yaml  gap discovery per review, verified-includes, local Ollama, $0
configs/remaining_reviews_ollama.yaml  Menon_2022 + van_der_Waal_2022 screening, local Ollama, $0
configs/ingest_all.yaml  all six reviews, screening disabled -- the fresh-clone/reproduction path
data/embeddings/         SPECTER2 vectors cached per review (gitignored)
data/asreview/           per-review CSV exports for the ASReview baseline (gitignored, SYNERGY text)
scripts/reproduce.sh     venv -> pinned install -> pytest -> ingest -> smoke harness, one command
tests/                   376 tests
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

| Review | Prevalence | Random TNR@95 | BM25 TNR@95 | BM25 WSS@95 | Model TNR@95 | Model Verif | Model Rec(v) |
|---|---|---|---|---|---|---|---|
| Smid_2020 | 1.0% | 0.029 | 0.568 | 0.513 | 0.113 | 91.7% | 0.308 |
| Nelson_2002 | 21.9% | 0.066 | 0.080 | 0.024 | 0.164 | 51.9% | 0.906 |

Model column: `qwen2.5:7b-instruct` via Ollama, `runs/20260918T060412811907Z-2556bbe54c`
(config `week08_ollama.yaml`; run twice, byte-identical, second run 100% cache
at $0). Verif is the fraction of decisions whose evidence span verified —
everything else became `unverified` and was scored as a referral, not a
prediction. Rec(v) is recall over verified decisions only; the Nelson_2002 rate
looks strong but rests on barely half the decisions being verified at all.

**Observed 15 September 2026 (rule 7).** The lexical baseline does the
opposite of the inflation expected below: BM25 over the published criteria
saves most of the reading on Smid_2020 (1.0%) and almost none on Nelson_2002
(21.9%), where it barely beats random. Not yet explained. One hypothesis to
check, not a conclusion: Nelson_2002's candidate set was retrieved for a
single topic (HRT), so the criteria vocabulary is shared by nearly every
record and cannot separate them, whereas Smid_2020's candidates are lexically
diverse. Random is one seed; do not read its two values as different.

**Observed 18 September 2026 (rule 7).** `gemini-2.5-flash-lite` returned
`404 NOT_FOUND — no longer available to new users` on the first live call,
even though Google's pricing page (`ai.google.dev/gemini-api/docs/pricing`)
still lists it as available with no deprecation notice — this account is most
likely gated as "new," not the model being globally withdrawn. The verified
working replacement, `gemini-3.5-flash-lite`, is confirmed at $0.30/$2.50 per
1M input/output tokens — about 4x `configs/week08_gemini.yaml`'s assumed
price. `google-genai==0.3.0` handles the new model's response shape fine
(the missing `thoughts_token_count` was already handled defensively). Rather
than eat the 4x price for week 8, added `ollama` as a third provider
(`slr/adapters/llm.py`, `OllamaProvider`) running `qwen2.5:7b-instruct` on the
author's own RTX 3070 (8GB VRAM) — $0 marginal cost, JSON-schema-constrained
output via Ollama's `format` parameter, same contract as `GeminiProvider`.
Smoke-tested on 5 real records: JSON mode held (no schema failures), 4/5
spans verified. `configs/week08_gemini.yaml` is kept as-is for a future
reported comparison; it is not run for the week 8 headline figures.

**Observed 18 September 2026, second entry (rule 7).** The full week 8 run
(`qwen2.5:7b-instruct`, both reviews, 2,993 records, $0) shows a large gap in
verification failure rate between reviews: 8.3% of Smid_2020 decisions failed
to verify vs. 48.1% of Nelson_2002's (`not_found` dominates: 358 of 393 total
failures). Not yet explained — candidate hypotheses, none checked yet: Qwen's
quoting discipline may degrade on shorter/simpler abstracts (Nelson_2002 has
more, per record, than Smid_2020), or on the higher-prevalence review the
model has more genuine matches to quote from and takes more liberty
paraphrasing them. Also pulled and smoke-tested `qwen3:8b` (5 records, 4/5
verified, JSON mode held even with its thinking mode on) as a candidate for
the week 10 model-tier comparison — not used for the week 8 headline run.

**21 September 2026 — data extraction, added outside the original schedule.**
The supervisor asked for a report this week showing extracted data (tables,
geographic view). Not in RQ1/RQ2 or the 15-week schedule, so built to fit the
project's own rules rather than as a one-off script: `slr/services/extract.py`
mirrors `screen.py` exactly — ask, validate shape, verify quote — per field
instead of per decision, reusing `verify_span` unchanged. New `extraction`
table (`SCHEMA_VERSION` 3 → 4; `data/slr.db` deleted and re-ingested — counts
matched exactly, 2,627/27 and 366/80). Ran over the week 8 run's 114
Nelson_2002 verified-includes, `qwen2.5:7b-instruct`, $0:

| Field | Verified | Not stated | Unverified |
|---|---|---|---|
| study_design | 102 | 7 | 5 |
| sample_size | 91 | 10 | 13 |
| country | 22 | 90 | 2 |
| key_finding | 110 | 0 | 4 |

`country` is the honest negative result: verified in under a fifth of
records. Nelson_2002's criteria don't require it, so most abstracts simply
don't say — reported `not_stated`, not guessed.

Two real bugs surfaced building this, both fixed at the `Provider`
architecture level, not patched around:

1. `OllamaProvider`/`GeminiProvider` hardcoded `RESPONSE_SCHEMA` to
   screening's shape. The first extraction run scored 0% on every field —
   Ollama's structured-output constraint was silently forcing the model into
   the wrong JSON shape regardless of the prompt. `Provider.complete` now
   takes an optional `response_schema`, defaulting to each provider's own
   schema (screening's callers are unchanged) but overridable per call.
2. `request_fingerprint` didn't hash `response_schema`, so the *second*
   extraction run silently served the first (broken) run's cached responses
   instead of raising `CacheMismatch` — exactly the staleness that fingerprint
   exists to catch. Fixed the same way: `response_schema` is now part of the
   hashed payload, but only when given, so screening's existing cache entries
   fingerprint identically to before (checked against the pre-migration DB
   backup). The 114 poisoned extraction cache rows were deleted.

Report published as an Artifact: KPI tiles per field, a country bar chart +
world map (only cleanly-resolvable single-country quotes are plotted; two
multi-region/multi-national answers are shown in the table but not mapped),
and the full 114-record table with per-field verified/not-stated/unverified
badges. Traces to `runs/20260920T122648310211Z-extract-705f89ab33`.

Also ran extraction on Smid_2020's 10 verified-includes
(`runs/20260920T130935713644Z-extract-454fea8b50`) as a direct comparison —
a cleaner result, 0 unverified on any field:

| Field | Verified | Not stated | Unverified |
|---|---|---|---|
| study_design | 10 | 0 | 0 |
| sample_size | 2 | 8 | 0 |
| country | 0 | 10 | 0 |
| key_finding | 10 | 0 | 0 |

`country` at 0/10 is a clean null result, not a gap: a Bayesian-estimation
simulation-methodology review has no real-world setting to state, and the
model said so every time rather than inventing one. `sample_size` mostly
`not_stated` too — several papers describe it as a simulated condition (e.g.
`"n = d·a, where d = 2, 3, 4 and 5"`) rather than a fixed number, correctly
quoted but not capturable by a single-value field. The published report now
switches between both reviews.

**Third review added: van_der_Valk_2021** (725 records, 12.3% prevalence,
medicine/psychology — hair cortisol and obesity). Ingest matched the
proposal exactly (725/89/12.3%). Screened with `qwen2.5:7b-instruct`
(`configs/valk2021_ollama.yaml`), run twice with `--require-clean`,
`metrics.json` byte-identical:

| Verif | Rec(v) | Rec(+h) | Saved | TNR@r |
|---|---|---|---|---|
| 39.3% | 0.320 | 0.809 | 37.8% | 0.138 |

Verification rate (39.3%) is lower than both Smid_2020 (91.7%) and
Nelson_2002 (51.9%) — across three reviews now, verification rate does not
track prevalence in any simple direction. Extracted from its 11
verified-includes (`runs/20260920T133746642566Z-extract-7b72d83b0a`) — the
noisiest extraction run of the three: one record failed JSON-shape
validation outright, and `key_finding` (96%+ verified in both other
reviews) only verified 8/11 here. With n=11 this could be noise; flagged,
not concluded. The report now switches across all three reviews.

**Fourth review added: Radjenovic_2013** (5,935 records, 0.8% prevalence,
software engineering — fault prediction). The largest review screened so
far and the only SE domain besides Smid_2020's CS-methodology one. Ingest
matched the proposal exactly (5935/48/0.8%, 0 without abstract). Screened
with `qwen2.5:7b-instruct` (`configs/radjenovic2013_ollama.yaml`), single
run (not run-twice — that property is already proven at this point):

| Verif | Rec(v) | Rec(+h) | Saved | TNR@r | AC1 |
|---|---|---|---|---|---|
| 35.6% | 0.925 | 0.938 | 33.4% | 0.209 | 0.950 |

Extracted from its 132 verified-includes
(`runs/20260921T090058751699Z-extract-e1e1617c75`) — the largest extraction
batch, and the clearest domain-generalisation result yet:

| Field | Verified | Not stated | Unverified |
|---|---|---|---|
| study_design | 47 | 83 | 2 |
| sample_size | 10 | 122 | 0 |
| country | 3 | 128 | 1 |
| key_finding | 129 | 2 | 1 |

`study_design` (35.6%) and `sample_size` (7.6%, the lowest of any review)
both collapse here: SE papers describe datasets, repositories and metrics,
not patient cohorts with a stated design and N — the extraction schema was
shaped by clinical-trial reporting conventions, and empirical software
engineering simply doesn't report that way. `country` is as sparse as
Smid_2020's (2.3% vs 0%), same reason. `key_finding` is the one field that
holds up regardless of domain: 97.7% here, 96-100% in every review so far.
The report now switches across all four reviews.

**A correction, made the same day it was noticed (rule 7).** Pausing the
Radjenovic_2013 screening run mid-way via a process kill was described to
the user as preserving the 1,509 records already screened, on the assumption
the response cache is written per record. It is not: `harness.py` only
commits the SQLite transaction once a review's full loop completes, so the
abrupt kill discarded the whole in-progress transaction. The resumed run
showed `0 cached_calls` of 5,935 and redid the review from scratch — still
$0, but ~28 minutes of the first session's compute was wasted. Worth a
proper fix (commit periodically within a review, not just at the end) before
this project pauses a long run again.

**21 September 2026 — week 9: dense retrieval, staged and verified.** Two
environment problems had to be resolved before any of this could run (both
now settled decisions, see below): the venv turned out to have been Python
3.13.5 all along (3.11 isn't installed on this machine), and SPECTER2 needs
the `adapters` library's proximity adapter, not plain `sentence-transformers`
— verified the adapter is genuinely active by comparing embeddings with vs.
without it (max abs diff 0.80), since the library prints a misleading "none
activated" warning during loading.

Built and run in three stages, each checked against BM25 before adding the
next layer, across all three ingested reviews:

| Review | BM25 TNR@95 | Dense TNR@95 | Hybrid TNR@95 | Rerank TNR@95 |
|---|---|---|---|---|
| Smid_2020 (1.0%) | 0.618 | 0.696 | 0.758 | 0.758 |
| Nelson_2002 (21.9%) | 0.094 | 0.178 | 0.129 | 0.129 |
| van_der_Valk_2021 (12.3%) | 0.068 | 0.181 | 0.108 | 0.108 |

(`runs/20260920T141238874787Z-2ecaa4d8d7` BM25,
`.../20260920T141257485896Z-423a543937` dense,
`.../20260920T153200090557Z-538ba6a5bc` hybrid,
`.../20260920T153252374417Z-da2f69f68d` rerank.)

**Dense alone already clears the exit test** on all three reviews, before
fusion or reranking. **RRF fusion is a tradeoff, not a strict win**: it helps
Smid_2020 (where BM25 is already strong, 0.618) and hurts the other two
(where BM25 is weak, 0.094/0.068) — pulling a weak lexical ranking into the
fusion drags it down there. **Rerank's TNR@95/WSS@95 are byte-identical to
hybrid's on every review** — verified this is real, not a stalled reranker:
hybrid and rerank orderings differ completely within the top-200 window
(confirmed directly, e.g. Smid_2020's top-10 work_ids are entirely
different), the tail past 200 is untouched by design, and all three
reviews' 95%-recall cutoffs (656, 325, 652) fall beyond that 200-record
window — reordering records whose set membership doesn't change can't move
a cutoff that's already past where the reordering happened. The
cross-encoder is doing real work; TNR@95 at this recall target simply can't
see it. A metric sensitive to top-200 ordering (precision@k, or a lower
recall target whose cutoff lands inside 200) would be needed to measure
reranking's actual contribution, if that number is wanted later.

**Observed 21 September 2026 (rule 7) — the BM25 baseline was not
corpus-independent, and every number resting on it has moved.**

`lexical_rank` queried the shared `work_fts` index and filtered by review
*afterwards*. SQLite's `bm25()` derives IDF from the whole index it is called
on, so a review's scores depended on which *other* reviews happened to be
ingested. Two independent observations of the same defect:

| Review | wk8 tag (2 reviews in DB) | wk9 tag (3 reviews) | old code, 4 reviews | **scoped (correct)** |
|---|---|---|---|---|
| Smid_2020 | 0.568 | 0.618 | 0.633 | **0.520** |
| Nelson_2002 | 0.080 | 0.094 | 0.077 | **0.038** |
| van_der_Valk_2021 | — | 0.068 | 0.074 | **0.049** |

(TNR@95. `corpus_sha256` is **identical** across every column — that
fingerprint covers the review's own text, not the rest of the index, so the
artefacts looked reproducible while the number drifted underneath them. This
is the same class of staleness `CacheMismatch` catches on the LLM path; the
retrieval path had no equivalent guard.)

Fixed by building a temporary FTS index holding only the review being ranked.
Verified bit-identical across a 3-review and 4-review database. Three
regression tests added in `tests/test_retrieve.py`; the corpus-independence
one fails on the pre-fix code (W3 scores −3.467 alone vs −22.143 with a
second review present) and passes after.

**Consequences, in order of how much they matter.**

*The corrected BM25 baseline is weaker than reported on all three reviews.*
Cross-review IDF was flattering it. Dense's margin over BM25 is therefore
**larger** than the week 9 table says — Smid_2020 +0.176 rather than +0.078,
Nelson_2002 +0.140 rather than +0.084, van_der_Valk_2021 +0.132 rather than
+0.113. The week 9 exit test passes more comfortably, not less.

*Dense figures are unaffected.* SPECTER2 embeddings are computed per record
and do not depend on what else is indexed. Verified by construction, not
assumed.

*Hybrid and rerank, re-run under commit `393db15` — the Smid_2020 gain
holds, the cost elsewhere got worse.*

| Review | BM25 (fixed) | Dense | Hybrid | Rerank |
|---|---|---|---|---|
| Smid_2020 (1.0%) | 0.520 | 0.696 | 0.757 | 0.757 |
| Nelson_2002 (21.9%) | 0.038 | 0.178 | 0.094 | 0.094 |
| van_der_Valk_2021 (12.3%) | 0.049 | 0.181 | 0.068 | 0.068 |

Hybrid's margin over dense on Smid_2020 is ~0.06 either side of the fix —
that gain was real, not an artefact of inflated BM25. But its cost on the
other two reviews is *worse* now that their BM25 is correctly much weaker:
hybrid trails dense by 0.084 on Nelson_2002 and 0.113 on van_der_Valk_2021,
both larger gaps than the pre-fix numbers showed. Rerank is still
byte-identical to hybrid on every review — cutoffs (658/335/678) still fall
past the 200-record reranking window, same explanation as before, unaffected
by this fix. Every strategy still beats the corrected BM25 on all three
reviews (`runs/20260921T072321083927Z-2ecaa4d8d7` through
`.../20260921T072421885220Z-da2f69f68d`).

*The `week-09` tag is kept as-is.* It records what was observed at the time.
Corrected runs are recorded alongside rather than overwriting it, because the
drift is itself a finding about the instrument, and a project arguing that
research tools should be checkable should not quietly rewrite its own numbers.

**Not yet done:**

- Never run against the real Gemini API for a reported figure. `configs/
  week08_gemini.yaml` is fixed to the working `gemini-3.5-flash-lite` model
  and its real price (2 October, see week 13) but running it still spends
  real money against the $50 ceiling — needs an explicit go-ahead, not just
  the config fix.
- Ethics application for the usability study — not submitted. This is the only
  item whose timing is outside the author's control. It gates week 13's
  human-subjects half. (The proposal, section 8.2, says approval is obtained
  in week 7.)

---

## Week 8 exit test: passed

*A stored configuration reproduces an identical metrics file, and a first
recall figure exists on two reviews.* Both halves done on real data:
`week08_ollama.yaml` (`qwen2.5:7b-instruct`) run twice with `--require-clean`,
`metrics.json` byte-identical, second run 100% cache at $0
(`runs/20260918T060412811907Z-2556bbe54c`,
`runs/20260918T072515193074Z-2556bbe54c`). Figures are in the table above.

The Gemini path (`configs/week08_gemini.yaml`) is deferred, not abandoned —
worth running later at `gemini-3.5-flash-lite`'s real price for the RQ2
cost/time comparison against the local arm, once the config's price and
ceiling are updated to match.

Khraisha et al. (2024) predict model accuracy looks better on the
high-prevalence review; week 8's figures instead show verification, not
accuracy, as the property that varies most sharply between these two — worth
keeping in view once week 10 adds real accuracy numbers.

## Week 9 exit test: passed

*Beats the lexical baseline on ≥3 reviews.* Cleared at every stage — dense,
hybrid and rerank all beat BM25's TNR@95 on all three reviews, more
comfortably after the BM25 corpus-independence fix (correcting the baseline
downward, not the treatments). Dense alone is the strongest single choice on
2 of 3 reviews (Nelson_2002, van_der_Valk_2021); hybrid is strongest on the
third (Smid_2020), and by a margin the fix confirmed as real rather than
explained away. No combination is uniformly best — worth carrying into week
10 as a real finding rather than picking one "winner" prematurely.

## Week 10 — prompt variants, model tiers, overridable, agreement

**The overridable property had no code, only a schema.** `human_decision`
existed in `db.py` since week 7 but nothing ever read or wrote it. Built
`slr/services/override.py` (`record_override` — refuses to override a record
never screened in that run; stays blind to `label_included`, the same
boundary `screen.py` keeps), `slr/eval/override_cli.py` (one disposition at a
time, prints the system's original proposal before writing), and
`slr/eval/override_report.py` (writes `overrides.json` into the run
directory, joining the override with ground truth — the one place that join
is allowed, kept out of `override.py` itself). 152 tests passing (was 136 at
the start of the week).

**23 September 2026 — full-subset consolidation run revealed a second cache
loss, this time from the 21 September schema migration (rule 7).**
`week10_full_subset.yaml` re-screens all four ingested reviews under one
`run_id`, same model/prompt/temperature/seed as every prior real run of
them — expected ~100% cache hit, effectively free. Only `Radjenovic_2013`
(5,935/5,935) actually was. `Smid_2020`, `van_der_Valk_2021` and
`Nelson_2002` — 3,718 records combined — re-screened live from scratch.
Cause: the 21 September `data/slr.db` delete-and-reingest for the extraction
`SCHEMA_VERSION` 3→4 migration wiped `cached_response` along with
everything else; only `Radjenovic_2013` was screened *after* that reset, so
it is the only review whose cache survived. Still $0 (local inference), and
the regenerated Smid_2020 figure (91.6% verified) is within noise of the
original (91.7%) — but it means every run directory recorded before 21
September is reproducible only as a *stored artifact*, not as a *free
replay*, until rescreened. `runs/20260921T112221881735Z-86c962f1d6`.

**Prompt variants v2 and v3 both made verification worse on Nelson_2002, not
better — a real negative result, not a tuning failure to paper over.**
`screen_v2` (step-by-step, asks for one sentence of reasoning before the
decision) dropped verification to 13.4%, and 149 of 366 responses failed
`schema_validation_failed` — adding a `reasoning` field ahead of the
required three in the prompt's own instructions measurably degraded
qwen2.5:7b-instruct's JSON discipline, it did not just add ignorable tokens.
`screen_v3` (terse, minimal rules) dropped to 13.9%, almost entirely
`not_found` (312/366) — the detailed evidence-span rules in `screen_v1` are
carrying real weight, not padding. `screen_v1` remains the prompt used
everywhere else. (`runs/20260922T115430121258Z-33c61120f3` v2,
`.../20260922T123132050251Z-6e54fdd202` v3, both vs. the v1 baseline at
`.../20260921T122043060429Z-df0fc175b2`.)

**Model tier 2 (qwen3:8b) is weaker on this task than qwen2.5:7b-instruct,
with a different failure shape.** 42.1% verified vs. qwen2.5's 51.9%, and
every failure was `not_found` — no `schema_validation_failed` at all, so
qwen3's JSON discipline held even with its thinking mode enabled, it simply
quotes less faithfully. Bigger and newer is not better here.
(`runs/20260922T123756418737Z-298d2bcad2`.)

**Reproducible now has a genuine number: inter-run Gwet AC1 = 1.0 across 5
cache-bypassed repeats.** `week10_repeat_nelson.yaml` (`cache_enabled:
false`, the one experiment the budget section permits to bypass the cache)
run 5 times against Nelson_2002, qwen2.5:7b-instruct, temperature 0, seed
42 — each a genuine independent call to the model, not a cache hit.
Verification rate held at 50.5–50.8% across all five, and `slr.eval.
inter_run` (`python -m slr.eval.inter_run`) computes AC1 = 1.0 on the 186
records verified in common: perfect agreement, not near-perfect. This is
the temperature-zero edge of Hida et al. (2026)'s reported 0.55–1.0 AC2
range (theirs on Gemini-2.5-Flash) — local Ollama inference on fixed
hardware reproduces it exactly, at least at this sample size. A weaker
version of the same claim ("identical config, cache hit, byte-identical
metrics.json") was already proven in weeks 7–8; this is the first time the
*model's actual output*, not the cache, was shown to be stable run to run.
(`runs/20260922T124547509237Z-9a8ec8f4db` through
`.../20260923T074803087022Z-9a8ec8f4db`, five runs.)

**Overridable demonstrated on 13 real Nelson_2002 records, not synthetic
ones.** Sampled 8 referrals (`unverified`, e.g. `not_found`) and 5 verified
decisions from the v1 baseline run, read each title/abstract in full against
the review's actual published criteria (comparison group of HRT nonusers,
outcomes reported; excluded if the population was risk-selected), and
recorded a genuine disposition for each via `override_cli.py` — blind to
`label_included` at decision time, the same way the model is. Result: 9 of
13 (69.2%) changed the system's proposal, 4 confirmed it. Checked against
ground truth afterward, as a bonus, not as part of the decision: 13/13
matched — including one case (`W2061891899`) where the model's `include`
had verified cleanly (the quote was real) but was substantively wrong: it
compared two *active* HRT regimens against each other with no non-user arm,
which the criteria require, and no verifier catches, because verification
checks whether a quote is real, not whether it supports the criterion it is
attached to. That is precisely the gap the overridable property exists to
cover, demonstrated on the project's own real data rather than argued in the
abstract. `runs/20260921T122043060429Z-df0fc175b2/overrides.json`.

## Week 10 exit test: passed

*Every property in the RQ1 table has a number.* Verifiable and accurate were
already numeric per review since week 8 (verification rate;
recall/precision over verified decisions; `agreement_ac1` vs. the human
label). Reproducible and overridable were the two gaps this week closed:
reproducible now has genuine inter-run AC1 (1.0, five cache-bypassed
repeats) beside the existing byte-identical-metrics.json property;
overridable now has a working mechanism and a real 69.2% override rate on
13 disposed records, 13/13 matching ground truth on review. Two negative
results land alongside the positive ones (rule 7): both new prompt variants
underperformed the existing one, and the second model tier underperformed
the first — worth carrying into week 11 as "screen_v1 and qwen2.5:7b-instruct
stay the default," not re-litigated every week without new evidence.

## Week 11 — gap discovery, built; go/no-go decision pending with supervisor

**Built as extraction's sibling, not a new pattern.** `slr/services/gap.py`
mirrors `extract.py`'s ask → validate shape → verify quote exactly, for one
implicit field: does this abstract state a research gap, limitation, or
future-work direction, in the authors' own words? `prompts/gap_v1.txt`
explicitly excludes a sentence describing what the paper itself did or
found — only a stated absence, uncertainty, or future direction counts.
Reused `ExtractConfig`/`extract_harness.py`'s shape directly
(`slr/eval/gap_harness.py`) rather than a new config class. The
`gap_statement` table existed since week 7 as an unused placeholder
(`sentence`/`category`/`cluster_id`, 0 rows); redesigned to the same
`run_id`/`source_run_id`/`value`/`evidence_span`/`span_verified`/
`verify_note` shape as extraction, plus `rating`/`rating_note` for the
precision check. Dropped and recreated locally rather than bumping
`SCHEMA_VERSION` — it was empty, so no re-ingest was needed (the cost of
that path was this week's own earlier lesson). 166 tests passing (was 159).

**Ran over every verified-include record from all four ingested reviews —
267 records, $0, local Ollama.** `gap_stated` rate: Nelson_2002 12/114
(10.5%), Smid_2020 1/10 (10.0%), van_der_Valk_2021 3/11 (27.3%),
Radjenovic_2013 5/132 (3.8%). 21 candidates total, not the 30 the schedule
anticipated — see the honest shortfall note below.

**Rated all 21, in full, against the actual abstracts (not just the model's
quoted span) — same method as week 10's override demonstration.** Pooled
precision (does the quote genuinely state a gap, per the task definition):
**19/21 = 90.5%**. Two false positives, both informative about how the
model fails: `W1970169800` quoted a "We conclude that..." risk-finding
sentence as if it were a gap (the verifier confirmed the quote was real; it
was still the wrong kind of sentence — verification checks the quote
exists, not that it answers the question asked, the same failure mode week
10's override catch demonstrated); `W2164782637` quoted "we give some
directions and ideas for future work" — announcing that a future-work
section exists, without stating any actual gap content, so it passes the
letter of the prompt's instructions while giving a researcher nothing to
act on.

**A second, more important distinction surfaced during rating, worth
tracking as its own number going forward: not every valid gap statement is
still open.** Of the 19 valid ones, 4 name a real gap in prior literature
that motivated the paper being read — and that the very same paper then
goes on to fill (e.g. Radjenović_2013's `W2120738100`: "This research did
not, however, distinguish among faults according to severity" — about
*prior* studies, immediately followed by "In this paper, we use logistic
regression... taking fault severity into account"). That is a genuine gap
statement in the authors' own words, but not an open one — a researcher
reading it as "here is unexplored territory" would be wrong, because the
paper in hand already explored it. Excluding those 4, the actionable
precision (a gap a future researcher could still pursue) is **15/21 =
71.4%**. Per-review split of the 21: valid/rated 12/12 Nelson_2002 (11
valid, 1 invalid), 1/1 Smid_2020, 3/3 van_der_Valk_2021, 5/5 Radjenovic_2013
(4 valid, 1 invalid) — full quotes and ratings in each run's
`gap_ratings.json`.

**24 September 2026 — the shortfall closed by ingesting the last two
reviews (path (a)); 74 statements now rated, not 21.** The first pass
found 21 because only 7.9% of the first four reviews' 267 verified-includes
state a gap. Ingested `Menon_2022` (975/74/7.6%) and `van_der_Waal_2022`
(1,970/33/1.7%) — both matched the proposal exactly — and screened them
with the same model/prompt (`runs/20260924T090935787946Z-88b91f8dc3`:
Menon 94.8% verified, van_der_Waal 39.3%). All six reviews are now
ingested and screened. Gap discovery over their 151 verified-includes
added 53 candidates, all rated in full:

| Review | Prev | Records | gap_stated | Valid | Invalid | Precision | Open-gap precision |
|---|---|---|---|---|---|---|---|
| Radjenovic_2013 | 0.8% | 132 | 5 (3.8%) | 4 | 1 | 80.0% | 40.0% |
| Smid_2020 | 1.0% | 10 | 1 (10.0%) | 1 | 0 | 100% | 0% |
| van_der_Waal_2022 | 1.7% | 82 | 17 (20.7%) | 13 | 4 | 76.5% | 52.9% |
| Menon_2022 | 7.6% | 69 | 36 (52.2%) | 33 | 3 | 91.7% | 88.9% |
| van_der_Valk_2021 | 12.3% | 11 | 3 (27.3%) | 3 | 0 | 100% | 100% |
| Nelson_2002 | 21.9% | 114 | 12 (10.5%) | 11 | 1 | 91.7% | 83.3% |

"Open-gap" excludes valid statements that name a gap the same paper then
fills. Per-review counts under about 15 (Smid_2020, van_der_Valk_2021) are
too small to read; do not lean on their 100%. Pooled for the checkpoint
only: **65/74 = 87.8% precision, 56/74 = 75.7% open-gap precision.**

**Menon_2022's 52% rate is domain, not over-triggering.** Its records are
themselves systematic reviews of environmental exposures, whose structured
Conclusions nearly always end "further studies are needed". The gap rate
varies from 3.8% to 52% by review and does not track prevalence
(prevalence 12.3% gives 27.3%, 21.9% gives 10.5%); it tracks the abstract's
genre. Software-engineering abstracts (Radjenović_2013, 3.8%) rarely state
gaps in the abstract at all, consistent with the extraction finding that
the field reports differently from medicine.

**New failure types found in the 53, beyond the first 21.** Rated strictly:
(1) a practice or policy recommendation ("better patient information is
needed", "toxicity tests need a more comprehensive approach") is not a
research gap — 3 invalid; (2) a lexical trigger — `W3119834449` was flagged
because the abstract says "a major gap was the information on alternative
therapies", meaning missing information in consent conversations, not a
research gap; (3) "limitations and future directions are discussed" — an
announcement with no content — recurred in Menon (2 more), the same type
as week 11's first pair. The strict practice-vs-research call is a
judgement, lowers precision, and is recorded per row in `rating_note`; a
looser reading would put precision near 90%. Rated by one person, once —
no second rater, so no inter-rater agreement for this precision figure.

**Go/no-go: data points to go, decision still not minuted.** 74 rated
statements exceed the plan's 30, and both pooled figures (87.8%, 75.7%) are
well above anything that would trigger the prior-art-retrieval fallback.
Recorded as evidence for the supervisor conversation, not as a decision
made on the author's behalf. The sharpest caveat to raise there: precision
is per-statement over what the model flagged; recall (abstracts that state
a gap which the model marked `not_stated`) has not been measured at all.

Run directories: `runs/20260923T102642236622Z-gap-3496ae576f` (Nelson_2002),
`.../20260923T102816243601Z-gap-80a180d02a` (Smid_2020),
`.../20260923T102825404365Z-gap-8002013514` (van_der_Valk_2021),
`.../20260923T102838078110Z-gap-c8a03baad8` (Radjenovic_2013),
`.../20260924T100941794221Z-gap-5665542565` (Menon_2022),
`.../20260924T101041926525Z-gap-3fe61354b0` (van_der_Waal_2022), each with
its own `gap_ratings.json`.

**25 September 2026 — gap recall measured, and it is much lower than
precision (rule 7).** Precision only looks at what the model flagged, so
`slr/eval/gap_recall.py` samples what it did *not*. A seeded draw of 10
`not_stated` records from each of Menon_2022, Radjenović_2013, Nelson_2002
and van_der_Waal_2022 (Smid_2020 and van_der_Valk_2021 have too few to
sample), plus 3 already-flagged records per review as controls, shuffled
into one sheet of 52 (title and abstract only). Labelled before any model
output was consulted, under a rule fixed in advance: the abstract states,
in the authors' own words, that something is unknown, unstudied, a
limitation, or needs further research; bare announcements and
practice/policy recommendations do not count (same rule as the precision
ratings). The sampled miss rate scales to each review's whole `not_stated`
pool; TP is the flagged records rated valid.

| Review | Prev | not_stated pool | Sampled | Misses | Recall (est.) | Recall, worst case | Open-gap recall (est.) |
|---|---|---|---|---|---|---|---|
| Radjenovic_2013 | 0.8% | 127 | 10 | 0 | 1.00 | 0.10 | 1.00 (worst 0.05) |
| van_der_Waal_2022 | 1.7% | 65 | 10 | 3 | 0.40 | 0.25 | 1.00 (worst 0.33) |
| Menon_2022 | 7.6% | 33 | 10 | 5 | 0.67 | 0.57 | 0.91 (worst 0.71) |
| Nelson_2002 | 21.9% | 102 | 10 | 1 | 0.52 | 0.21 | 0.50 (worst 0.20) |

"Worst case" uses the upper end of the 95% Wilson interval on the miss
rate. With 10 per review every interval is wide (Radjenović_2013: zero
misses in 10 still allows recall as low as 0.10), so read the point
estimates as direction, not as figures to quote alone.
`runs/20260924T120813705057Z-gaprecall-d6901cb0a0`.

**What the model misses, and why that matters more than the number.** 9 of
the 40 sampled `not_stated` abstracts (22.5%) did state a gap. 7 of the 9
are *motivating* gaps ("little is known about...", "remains inconclusive",
"limited research has investigated..."), 1 is "evidence is insufficient",
and 1 is a plain miss: Menon's renal-cell-carcinoma review says "Further
investigation is warranted, especially for folate and vitamin B6" and was
marked `not_stated`. The pattern fits `gap_v1`'s own wording — it tells the
model that a sentence describing what the paper itself set out to do is not
a gap, and to answer `not_stated` in doubt, so a motivating gap that reads
like the paper's aim gets suppressed. That is a hypothesis about the prompt,
not something tested. Read the two recall columns together: the model is
a high-precision, low-recall detector of literal gap statements, and a
better one for future-work statements specifically (open-gap recall 0.5–1.0,
but on 1 miss at most per review).

**The controls.** 11 of 12 flagged controls I labelled blind agreed with my
earlier ratings; the one disagreement compared an abstract-level label
(yes, human studies are needed) with an earlier quote-level rating
(invalid: the quoted sentence was a regulatory recommendation). The
controls are only partly blind — I recognised several from the earlier
rating pass — so this is a weak check on my own consistency, not a
measure of it. The 40 `not_stated` items, which carry the recall
estimate, were not recognisable.

**Limits.** One labeller, no second rater. Several labels are borderline
calls (`controversial`, `inconclusive`, `work is underway`) and I marked
those positive; a stricter rule would lower the miss rate. Smid_2020 and
van_der_Valk_2021 are unsampled. Not pooled, per rule 5.

**Consequence for the go/no-go.** The 87.8% precision figure alone would
overstate what was built. The honest description for the supervisor is: gap
discovery surfaces statements that are almost always real gaps, but finds
perhaps half of the literal gap statements, and fewer of the motivating
ones. Whether that is enough depends on the use — as a "here are stated
gaps" surfacer it is fine; as a claim of coverage it is not. A `gap_v2`
that accepts motivating gaps as a separate category is the obvious
candidate, but week 10's prompt variants both made things worse, so it
needs the same discipline: a new prompt version, a full rerun, and a
re-rating, not an edit.

**25 September 2026 — extraction now covers all six reviews, and one
report shows everything.** Menon_2022 and van_der_Waal_2022 had been screened
and gap-analysed but not extracted; ran them (`qwen2.5:7b-instruct`, $0):

| Review | Prev | Verified includes | study_design | sample_size | country | key_finding |
|---|---|---|---|---|---|---|
| van_der_Waal_2022 | 1.7% | 82 | 46 | 69 | 25 | 76 |
| Menon_2022 | 7.6% | 69 | 69 | 35 | 6 | 66 |

(Verified counts; `runs/20260924T122137987321Z-extract-1d1c17652a` and
`runs/20260924T121711794197Z-extract-69af3c168d`.) `study_design` verifies in
100% of Menon_2022's records because they are all systematic reviews and say
so; the same field is 36% for Radjenovic_2013, so the field's coverage tracks
how a domain writes abstracts, not the model. A review of reviews also reports
`sample_size` differently (35 of 69), usually as a count of included studies.

Published an Artifact, "Extraction Atlas", showing all 418 verified-include
papers with the screening quote, the four fields, and the gap statement with
its rating, each with its source sentence and verification status; six
reviews side by side with prevalence beside them (never pooled), per-review
field coverage, gap breakdown, and a country map. The map is inline SVG
baked into the page, because the Artifact CSP blocks the runtime fetch that
a map library needs. 50 country mentions are plotted; 8 name only a region
and stay in the table. The report is built from the run directories listed in
its "Where every number comes from" section; it is a display and computes no
new figure. It quotes short source sentences but no abstracts (SYNERGY
abstracts stay out of git and out of published pages).

## Week 12 — FastAPI + 5 Streamlit panels, built; exit test not yet run

**Thin layer over what already existed, same discipline as every service
since `extract.py`.** `slr/api/app.py`: every route reads a harness's run
directory or the tables it wrote (`screening_decision`, `extraction`,
`gap_statement`), or calls a service function directly (`retrieve.rank`,
`override.record_override`, `screen.screen_record`). No route computes a
figure a CLI run wouldn't also produce. `slr/api/runs_index.py` picks the
"current" run per review per harness kind by scanning `runs/*/metrics.json`
— directory names sort chronologically, so the latest match wins. One
route writes new data: `POST /query/screen`, a live screen of up to 15
specific records for the panel below, into an `api-*` run_id the run-index
and `report_tables.py` both ignore — an interactive demo, not a reported
figure, so it doesn't need `--require-clean`.

**A real threading bug, found by the API's own tests, not a test
artifact.** FastAPI dispatches a sync dependency and the sync route body
to separate threadpool workers; a connection opened in `get_conn` could be
handed to a different OS thread than it was created in. sqlite3 connections
are thread-affine by default, so this would have failed intermittently
under real traffic, not just in tests. Fixed at the source: `slr.db.
connect()` gained `check_same_thread` (default `True`, every CLI harness
unchanged); the API's dependency is the only caller that passes `False`,
since its connection is used sequentially within one request, never
concurrently.

**Five panels, each calling the API and computing nothing itself:** Search
& Screen (rank candidates with any of the five strategies, default query =
the review's own published criteria, then screen up to 15 live and watch
verified quotes arrive — this is the page the exit test runs on), Results
& Override (browse a run's decisions, dispose of any of them), Extraction
(per-field coverage, then any paper's four fields with their source
sentences), Gap Discovery (every statement found, with its rating and
open/motivating split), Trust Dashboard (the RQ1 table, live per review —
reproducibility and gap recall are shown as the one-off measurements they
are, not fabricated as per-review live numbers, since both took a
dedicated multi-run or blind-labelling pass to produce, not a single
query).

**Tested two ways.** Streamlit's `AppTest` drives each page's real widgets
(form submit, multiselect, button click) against `api_client` monkeypatched
to canned data shaped like the real responses — no server needed, and it
caught a real bug: the Trust Dashboard scaled "Verified" and "Overridden"
to a percentage *after* the dataframe had already been built and passed to
`st.dataframe`, so the raw fraction displayed instead. Separately, verified
live end-to-end against the real six-review database and a real Ollama
call: `uvicorn` + `streamlit` both running, screenshotted with a small
custom CDP client (`websockets` + `httpx`) rather than headless Edge's own
`--screenshot` flag, which fires at the `load` event — before a Streamlit
page's actual content arrives over its websocket connection, so every
first attempt captured only the loading skeleton. All five panels render
correctly against real data; Trust Dashboard's live numbers
(verification_rate, AC1, prevalence per review) match `CLAUDE.md`'s
recorded figures exactly, and a real BM25 query against Menon_2022 through
Search & Screen returned real ranked candidates.

**The exit test itself has not been run.** "Someone other than the author
completes a query unassisted" needs an actual second person at the
keyboard — the mechanism is built and verified working, but that is not
the same claim, and it isn't mine to certify on the author's behalf. Marked
open until it happens.

Running it:

```bash
uvicorn slr.api.app:app
streamlit run app/Home.py
```

fastapi/uvicorn/streamlit were pinned in `requirements.txt` since project
setup but never installed; installed now at the pinned versions
(0.115.5/0.32.1/1.40.2). 202 tests passing (was 192).

## Week 13 — hardening, reproduction script, ASReview baseline

**2 October 2026 — the fresh-clone exit test, actually run, not assumed.**
"A fresh clone runs on a second machine" had never been tried: `SETUP.md`
still said Python 3.11 (the venv has been 3.13 since week 9, see the
decisions log) and its data step was `python -m synergy_dataset get` with
no concrete ingest command. Fixed both docs, added `configs/
ingest_all.yaml` (all six reviews, screening disabled, one command) and
`scripts/reproduce.sh` (venv → pinned install → `pytest` → ingest → smoke
harness, the exit test as a runnable script, not a paragraph of
instructions to follow by hand). Then actually tried it: cloned the
repository into an isolated directory with nothing carried over, built a
new venv from zero, and ran the whole chain. Everything passed on the
first real attempt: 215/215 tests, then the exact six-review record counts
this file already reports (12,598 total), then a clean harness run writing
its own run directory. Deleted the isolated clone afterward; nothing about
it is kept.

**Also fixed: `configs/week08_gemini.yaml` priced the now-blocked model.**
It still assumed `gemini-2.5-flash-lite` at $0.10/$0.40 per 1M tokens — the
18 September note already recorded that model as 404'd for this account
and `gemini-3.5-flash-lite` as the verified-working replacement at roughly
4x the price. The config now points at the real model with its real price
($0.30/$2.50) and a ceiling raised to $2.50 to match (est. cost ~$1.65 for
both reviews, up from the stale ~$0.40 estimate). Not run — that spends
real money against the $50 ceiling and needs an explicit go-ahead, which
this is not.

**Week 14's ASReview baseline, pulled forward and run — the sharpest
negative result for this project's own retrieval work so far.** ASReview
is run as an external tool, per the standing decision: `slr/eval/
asreview_baseline.py` exports one review to the plain CSV ASReview's own
reader recognises natively (`title`/`abstract`/`label_included` are column
names it already knows, because that's SYNERGY's own convention — no
reimplementation, no reshaping), then `asreview simulate` (its own CLI,
`-m nb -q max -e tfidf`, seed 42) runs its active-learning loop locally, $0.
`slr/eval/asreview_report.py` turns the result into the *same*
`ranking_metrics()` figure every BM25/dense/hybrid/rerank number in this
file already uses — not a second formula that happens to share a name.

One wrinkle, handled explicitly rather than glossed over: `--stop_if min`
means ASReview stops the moment every relevant record is found, so records
after that point were never ranked at all. The report script appends them
afterward in their original dataset order. This is provably harmless to
the figure: the 95%-recall cutoff `ranking_metrics` looks for always falls
*before* the 100%-recall point where ASReview stopped, so nothing appended
after that point can change which records are counted as found before the
cutoff. Verified by construction, not assumed — `tests/test_asreview_report.py`
checks the reassembly directly.

**2 October 2026, completed — all six reviews, not just two.** Hit one more
real bug extending to the rest: `asreview simulate` crashed outright on
Menon_2022 with `UnicodeEncodeError` printing its "prior knowledge" preview
— the exact same Windows cp1252-console bug `one_paper.py` was fixed for in
week 12, this time inside ASReview's own CLI, not this project's code.
Worked around with `PYTHONIOENCODING=utf-8` on the subprocess rather than
patching a third-party package; no code change needed, nothing to upstream
from here. Same benign tmp-directory `PermissionError` as Nelson_2002/
Smid_2020 on every run (ASReview trying to delete its own open sqlite
handle on Windows after finishing) — cosmetic, the project file is already
written in full by that point, confirmed by reading it back successfully
every time.

| Review | Prev | Our best ranking (TNR@95) | ASReview TNR@95 | ASReview WSS@95 |
|---|---|---|---|---|
| Radjenovic_2013 | 0.8% | not run (see below) | 0.947 | 0.890 |
| Smid_2020 | 1.0% | 0.757 (hybrid/rerank) | **0.822** | 0.763 |
| van_der_Waal_2022 | 1.7% | not run (see below) | 0.813 | 0.750 |
| Menon_2022 | 7.6% | not run (see below) | 0.723 | 0.621 |
| van_der_Valk_2021 | 12.3% | 0.181 (dense) | **0.500** | 0.394 |
| Nelson_2002 | 21.9% | 0.178 (dense) | **0.497** | 0.349 |

"Our best ranking" is only filled in for the three reviews week 9 built
dense/hybrid/rerank for — Radjenovic_2013, Menon_2022 and van_der_Waal_2022
never got that treatment (week 9's dense retrieval exit test only needed
three reviews to clear, and the schedule moved on). Their screening-
confidence ordering has its own TNR@r in the week 8/11 tables, but that's a
different ranking mechanism (an LLM's confidence, not a retrieval score)
and mixing the two in one column would compare things that aren't the same
kind of number — left blank rather than filled with something misleading.

ASReview's active learner beats every ranking this project has built, on
all three reviews where a comparison is possible — unsurprising in
hindsight (it sees true labels as it goes and retrains; every strategy
here ranks once, from nothing, and never updates) — and the pattern in the
*margin* holds up now with a third data point, not just two: tiny on
Smid_2020 (+0.065, the lowest-prevalence review of the three), then
roughly the same large margin on both van_der_Valk_2021 (+0.319) and
Nelson_2002 (+0.319) despite their prevalence differing by almost 10
points. Reads as a floor effect more than a straight line with prevalence:
below some threshold of positive examples the active learner hasn't
learned enough to pull ahead by much; above it, the margin is large and
roughly flat. Three points is not enough to claim the shape of that curve,
only that it isn't simply "margin grows with prevalence." Worth returning
to in week 15's limitations section either way: this project's RQ1 is
about trust in LLM-made decisions, not about beating a dedicated
active-learning tool at ranking, but the comparison is honest to report
(rule 7), and it's a legitimate reason a future version might add adaptive
reranking rather than a single static pass.

219 tests passing (was 215).

**3 October 2026 — Discover, added outside the schedule, at the user's
request.** The five built panels only ever search the six ingested
reviews; asked directly, that's a real gap between what a reviewer expects
a "literature search" tool to do and what's built. Added a sixth panel
that searches the open web (OpenAlex, free, keyless, CC0 — unlike
SYNERGY, its abstracts are fine to show live) and runs every result
through the *same* ask → validate → verify extraction and gap-discovery
pipeline as the rest of the project, unchanged: `extract_record`/
`extract_gap` only need a title and an abstract, and don't care where one
came from.

Deliberately kept outside the evaluation corpus, the same discipline as
everywhere else in this project: discovered records carry
`review="_discover"` (never a real review name), are never written to the
`work` table, and the one route that calls it, `POST /discover`, follows
`POST /query/screen`'s own precedent of being an interactive feature, not
a reported figure. Screening/inclusion decisions don't apply here — there's
no published eligibility criteria for an ad-hoc query — so Discover only
extracts and gap-checks, it doesn't include/exclude.

One real constraint surfaced building it: OpenAlex only has a
redistributable abstract for roughly half of what it indexes (publisher
licensing withholds the rest); `search_openalex` fetches extra results and
filters to ones with an abstract, rather than silently handing extraction
nothing to work with. Verified live, not just against mocks: a real query
("hormone therapy cardiovascular risk") returned two real, previously-
unseen papers — one fully verified (cohort study, 4,958 participants, its
key finding quoted verbatim), one `schema_validation_failed` on every
field, the same honest failure mode already documented for the ingested
corpus, not a new bug. 230 tests passing (was 219).

**4 October 2026 — fourteen charts, built as one data layer rather than
fourteen one-offs.** The five panels showed tables and metrics but not a
single chart, including the one chart every screening-prioritisation paper
leads with (recall against records read). Built `slr/eval/charts.py`: one
pure function per chart, returning plain dicts, plotting nothing.
`app/plots.py` holds the Altair builders, eight `/charts/*` routes wire them
up, and no panel computes anything itself — the same discipline as every
service since `extract.py`.

Deliberately placed in `slr/eval` rather than `slr/api` or `app/`: four of
these functions read `work.label_included` (the recall curve, prevalence,
the verification/recall scatter), and rule 4 permits ground truth to be read
inside `slr/eval` and nowhere else. A chart needing it has to live there.
`test_chart_routes_never_return_ground_truth` asserts no route hands a
per-record label back out.

What landed, by panel: **Trust** — verification rate ordered by prevalence,
a failure-type heatmap (row-normalised, because Radjenović_2013 has sixteen
times more records than Nelson_2002 and raw counts show one bright row),
the confidence histogram split by verification, a verification-vs-recall
scatter, override outcomes, and latency/cache. **Search & Screen** — the
recall curve with the random diagonal and the 95% cutoff, plus a semantic
map. **Extraction** — per-field status bars and the six-review coverage
heatmap. **Gaps** — gap rate by review, and precision beside recall.
**Home** — prevalence and publication years.

**The confidence histogram is the one that earns its place.** It renders the
calibration finding directly: mean confidence 0.813 on decisions whose quote
verified, 0.798 on decisions whose quote was invented — a 0.015 gap across
23,148 decisions. The model is as confident when it fabricates as when it
quotes correctly. That is the argument for the span verifier in one picture,
and for `unverified` being a referral rather than a prediction: no
confidence threshold could have separated these two distributions. Drawn as
two overlaid outlines rather than a stacked bar, because whether they sit on
top of each other *is* the question.

**Three charts deliberately not built, and said so on the page rather than
drawn empty.** Country map, venue breakdown, language split: `venue`,
`publisher`, `country` and `language` are 0 of 12,598 non-null, because
ingest never populated them. Home lists them as "not chartable yet" with the
reason. Same principle inside the heatmaps: a field never extracted for a
review is left blank, not shaded 0% — "never attempted" and "attempted and
never verified" are different findings and must not share a colour.

**Two things the charts are tested to not do.** `charts.recall_curve`'s 95%
crossing is asserted equal to `metrics.ranking_metrics`'s `cutoff` on the
same ranking, so the curve cannot drift from the TNR@95 in the table beside
it. And five tests run against the real `data/slr.db`, asserting the charts
reproduce figures this file already records — the corpus table (12,598
records, 351 included), week 11's per-review gap counts, and the calibration
gap. If a recorded figure and its chart ever disagree, a test says so rather
than a reader noticing.

Downsampling keeps every include: a 5,935-record curve sends ~400 points,
but never drops a position where the curve steps up, and the semantic map
samples excludes only — Smid_2020's 27 includes among 2,627 records would
otherwise be invisible. The map projects by hand-rolled PCA rather than
t-SNE or UMAP: no new pinned dependency, deterministic, and linear, so
distance on the plot can honestly be described as distance in the embedding
space projected. It reports variance explained (~21%) so clusters aren't
over-read.

`altair==5.5.0` pinned explicitly — Streamlit pulled it in already, but
`plots.py` imports it directly now. 283 tests passing (was 230): 28 in
`test_charts.py`, 13 new API route tests, 11 new page tests. Verified end to
end against the real six-review database — all 8 routes, 35 Vega-Lite specs
validated on real data, and Streamlit's own `AppTest` driving every panel.

**Rendering confirmed by the author, by hand, repeatedly** — `uvicorn` +
`streamlit` against the live database, all six panels, multiple passes. Worth
recording separately: a validated Vega-Lite spec proves the chart is
well-formed, not that it is legible or that the axes say what they should.
That second claim needs a person looking at it, and now has one.

**4 October 2026, second entry — the dashboard was demoing the evaluation,
not the product. Restructured.** Asked what the six reviews were useful for
in the product, the honest answer was: nothing. They are the test harness.
But five of six panels showed only them, so the tool demoed as a report
about six old medical reviews rather than as something a researcher would
use. That is a presentation defect with two weeks to submission, and it was
worth fixing before the report describes a thing the examiner then opens and
misreads.

**The missing capability, not just the missing framing.** Discover could
search live literature and extract from it, but could not *screen* it —
there is no published eligibility criteria for an ad-hoc query, so there was
nothing to judge include/exclude against. Fixed by having the user supply
their own criteria in plain sentences. `screen_record` already took
`criteria` as a plain string, so this needed no new screening code path at
all: the same `screen_v1` prompt, the same shape validation, the same span
verifier, pointed at a question someone typed a minute ago. The
architecture's one real test and it passed.

**A genuine cache problem this surfaced, fixed without bypassing the cache.**
The response cache is keyed on (model, prompt_version, review, work_id). On
the ingested corpus a review's criteria are pinned, so that key is stable.
Ad-hoc criteria are not: two different criteria for the same OpenAlex paper
collide on one key, the request fingerprint correctly spots the mismatch,
and `CacheMismatch` aborts a query the user did nothing wrong in.
`criteria_prompt_version` folds a 12-hex digest of the criteria text into
the version string, giving each distinct set its own namespace. Note what
this is *not*: the cache is still checked before every call, so re-running
an identical session is still free. Only a genuinely different question is
treated as a different request — the budget rule that the week 10
repeated-run is the only permitted cache bypass is untouched.

**Extraction still only reads verified includes, on this path too.** A paper
the criteria reject, or whose decision was referred, is reported with its
decision and quote and is *not* extracted — the same boundary
`extract_harness` keeps. Pulling study data out of a paper the user's
criteria exclude would be inventing a result. With no criteria at all,
nothing is screened and `decision` stays `None`: the system does not guess
an include/exclude when it has nothing to judge against.

**The restructure.** `Home.py` is now a search box — "What are you
researching?" — that hands the topic to the review page. Six panels renamed
so the sidebar reads product-first: `1_Run_a_Review` (the product), then
`2_Validation_Trust` through `6_Validation_Gaps`. Every validation page
carries a banner saying it is evidence rather than the tool, and points at
Run a review; a test asserts all five do, because a restructure that only
moves the confusion somewhere less visible is worse than none.
`6_Discover.py` is deleted — the new page is Discover plus screening, and
keeping two would be two half-answers. The corpus charts (prevalence,
publication years) moved from Home to `2_Validation_Trust`: how hard a
review is *is* validation evidence, and a verification rate is unreadable
without it.

**Home states the three recorded shortfalls on the front page** — the 99%
verification target missed, roughly half the stated gaps found, ASReview
out-ranking this project's retrieval on every review where a comparison
exists — with a test asserting they are there. A landing page that only
claims success is a sales page, and rule 7 does not stop applying because
the reader is non-technical.

**The product path produces no reported figure, by construction.** There is
no ground truth for a topic typed a minute ago, so nothing on Run a Review
is scored; the page says so and points at the validation pages for "how
often is it right?". Discovered records still carry `review="_discover"`,
are never written to `work`, and `run_discover` persists nothing at all.
`test_screening_ad_hoc_records_never_reaches_the_evaluation_corpus` asserts
all four tables stay empty after a session and that `_discover` is not in
`config.SUBSET`, so no config could point a reported run at it even by
mistake.

307 tests passing (was 283). Verified end to end through the real API route
with the real prompts and the real verifier: searched, screened against
supplied criteria, quote verified, extracted, gap found. The one rendering
rule worth naming — an `include` whose quote was not found in the abstract
renders as "Needs your eye", never as "Keep" — has its own test, because
that is the span verifier's entire argument surfacing in the UI rather than
only in the data.

**5 October 2026 — the ablation and the error typology, the two promised
Table 9 measurements that had no number at all. Both change what this
project can honestly claim.**

**Everything here is computed from recorded data. No model was called, and
it cost $0.** The ablation reconstructs the un-verified system exactly
rather than approximating it: `screen.py` overwrites a decision with
`unverified` when its quote fails, but `cached_response.raw_response` still
holds the model's literal answer, keyed on (model, prompt_version, review,
work_id). All 12,598 decisions were recoverable, so the counterfactual runs
on the full corpus, not a sample. `test_every_decision_is_recoverable_on_the_real_corpus`
fails if the cache is ever wiped again, rather than the ablation quietly
shrinking.

**A methodological trap, avoided and then encoded.** The shipped system's
recall is over verified decisions *only* — referred records are excluded
from the denominator rather than counted as misses. Setting that figure
beside a policy that scores every record would credit the verifier for the
records it declined to answer. `PolicyResult.comparable` marks it, the
report prints it in a separate section, and a test asserts it stays out of
the comparison table. The only like-for-like pair is "trust the model" vs
"refer unverified to a human", both scored over every record.

**The verifier buys recall on every review, and it is not close.**

| Review | Prev | Recall trusting the model | Recall with the gate | Δ | Read w/ trust | Read w/ gate |
|---|---|---|---|---|---|---|
| Radjenovic_2013 | 0.8% | 0.771 | 0.938 | +0.167 | 141 | 3,953 |
| Smid_2020 | 1.0% | 0.296 | 0.333 | +0.037 | 9 | 229 |
| van_der_Waal_2022 | 1.7% | 0.424 | 0.788 | +0.364 | 85 | 1,278 |
| Menon_2022 | 7.6% | 0.703 | 0.730 | +0.027 | 70 | 120 |
| van_der_Valk_2021 | 12.3% | 0.112 | 0.809 | **+0.697** | 13 | 451 |
| Nelson_2002 | 21.9% | 0.688 | 0.963 | +0.275 | 134 | 291 |

The records whose quotes fail are disproportionately the ones the model got
wrong, so refusing to trust them recovers included papers that trusting the
model drops. van_der_Valk_2021 is the extreme case: recall 0.112 → 0.809.
The price is reading — 13 records becomes 451, and on Radjenovic_2013 141
becomes 3,953. **That is the honest trade and it should be reported as a
trade, not a win.**

**0.2% of verification failures are fabrication. 97.8% are the model
quoting the eligibility criteria back at us.** `verify_note` says
`not_found` on 98.6% of failures, which is true and useless — it cannot
tell a reworded real sentence from an invented one. `slr/eval/
error_typology.py` classifies each failed span against the source using
`verify.normalise`, so a category cannot disagree with the decision that
produced it. The first pass reported 97% "fabricated", which was alarming
enough to check rather than write down — and the spans turned out to be
lines like *"Studies discussing software metrics in a context other than
software fault prediction (e.g. maintainability) OR."*, which is
Radjenovic_2013's own published exclusion criterion, sitting in the prompt.

| Review | Failures | echoed_criteria | near_paraphrase | stitched | fabricated | other |
|---|---|---|---|---|---|---|
| Menon_2022 | 51 | 36 (71%) | 6 | 8 | 0 | 1 |
| Nelson_2002 | 181 | 178 (98%) | 2 | 1 | 0 | 0 |
| Radjenovic_2013 | 3,821 | 3,799 (99%) | 12 | 5 | 3 | 2 |
| Smid_2020 | 220 | 156 (71%) | 26 | 31 | 2 | 5 |
| van_der_Valk_2021 | 440 | 432 (98%) | 4 | 3 | 1 | 0 |
| van_der_Waal_2022 | 1,196 | 1,177 (98%) | 3 | 9 | 6 | 1 |
| **All six** | **5,909** | **5,778 (97.8%)** | 53 (0.9%) | 57 (1.0%) | **12 (0.2%)** | 9 |

**This reframes the project's central finding, and mostly in the model's
favour.** `qwen2.5:7b-instruct` almost never invents a quote — 12 times in
5,909 failures. What it does, overwhelmingly, is answer a different
question: asked for the sentence that justifies the decision, it returns the
*rule* it applied instead of the *evidence* for applying it. That is a
prompt-comprehension failure, not a honesty failure, and it is plausibly
fixable. A `screen_v4` that states the span must come from the abstract and
never from the criteria is the obvious candidate — but week 10's two prompt
variants both made things worse, so it needs the same discipline: a new
version, a full rerun, a re-rating, not an edit.

**The caveat that keeps this honest.** If the dominant failure is fixable by
prompt design, then the verification rate reported throughout this project
is partly a measure of *prompt quality*, not only of model trustworthiness.
The verifier still does exactly what RQ1 claims — it refuses to present an
unbackable decision as a fact — but the headline "only 35–95% of decisions
verify" should be read as "the prompt leaks the criteria into the answer
slot", not as "the model hallucinates a third of the time". Week 15's
limitations section has to say that plainly.

**Being unverifiable is not the same as being wrong.** Of the 5,778 criteria
echoes, only 113 (2.0%) were also factually wrong decisions; genuine
fabrications were wrong 8.3% of the time, stitched quotes 7.0%. So the gate
refers a great many decisions that would have been right — that is the cost
column in the table above, now with a cause attached to it.

A seeded, review-stratified sample of 50 failures is written as a blind
rating sheet (`rating_sheet.json`, automatic labels withheld behind an
underscore prefix), the same method the week 11 gap-recall pass used.
**Not yet rated by hand** — the automatic labels are unvalidated until that
pass happens, and the figures above should carry that caveat until it does.

Run directories: `runs/20261005T081610581869Z-ablation-414c762b99`,
`runs/20261005T082109115224Z-typology-414c762b99`. The ablation also
reproduces week 9's corrected retrieval figures from their own run
directories (0.520/0.696/0.757/0.757 on Smid_2020), which is a cross-check
that the ablation reads the same artefacts the report does.

339 tests passing (was 307): 19 for the ablation, 20 for the typology.

**7 October 2026 — Europe PMC's open-access flag does not mean the full
text is there (rule 7).** Found on the first live run of full-text
extraction, and worth recording because the symptom looks exactly like the
system underperforming.

`PMC7508247` (Association between vitamin D supplementation and mortality,
BMJ, doi 10.1136/bmj.m2329) is flagged `isOpenAccess = Y`. Its
`fullTextXML` is **1,058 characters**: one untitled section, and no
`table-wrap`, `fig` or `disp-formula` element anywhere in the document. A
BMJ meta-analysis runs 30,000–50,000 characters with forest plots and
summary tables. Nothing in the API response distinguishes this stub from a
complete paper.

The extraction then reported 1 of 5 fields verified, 0 tables, 0 figures —
which reads as weak extraction and is nothing of the sort. The model was
shown a thousand characters and said "not stated" to the four fields that
text does not contain, which is the correct answer. The one field it did
fill it filled correctly, with a real confidence interval quoted verbatim:
*"the risk ratio and 95% confidence interval of cancer mortality changed
from 0.84 (95% confidence interval 0.74 to 0.95) to 0.85 (0.74 to 0.97)."*

`FullText.is_fragment` now names the state: a body under 5,000 characters
**and** no section headings, tables or figures. Both signals together,
because either alone has honest exceptions — a short letter has the first,
a genuinely table-free paper has part of the second. The API says so
plainly rather than letting a reader blame the extraction.

**Two things this changes for the report.** First, the earlier estimate
that full-text coverage is limited by domain was too generous: coverage is
limited by domain *and* by the open-access flag overstating what is
actually served, and the second is invisible until you parse the document.
Second, this is a third instance of the pattern this project keeps hitting
— a figure that looks like a model failure turning out to be an instrument
problem (the BM25 corpus-independence drift, the 97.8% criteria echoes, and
now this). Worth naming in the limitations section as a methodological
point: an evaluation of an LLM pipeline measures the whole instrument, and
attributing a number to the model before checking the plumbing is how most
of these would have been mis-reported.

`scripts/inspect_fulltext.py` exists for exactly this: it prints what
Europe PMC actually sent — body length, sections, tables, figures, and
which XML tags are present — so a thin record can be told from a parser bug
without guessing.

**7 October 2026, second entry — full-text extraction confirmed on live
data, and a third instance of one failure pattern.**

`PMC10248995` ("Guidance to best tools and practices for systematic
reviews", *Systematic Reviews*) is the first complete paper the pipeline
has read: 383,611 characters of JATS, 75,211 characters of body across 40
sections, **16 tables parsed with their captions and row counts**, 1 figure
with its caption *and* the sentence that cites it — *"we integrate them
into a practical scheme (see Fig. 1)"* — found by the mention matcher. All
six of the requested extraction features work on real literature, not just
fixtures.

Three honest limits surfaced in the same run, all now reported rather than
hidden:

**Truncation is severe on long papers.** 75,211 characters of body, 24,000
sent to the model — 32%. The prompt source prioritises results,
limitations and discussion so truncation eats the introduction first, but a
field marked "not stated" may genuinely be in the two thirds that were cut.
The API note now says how much of the paper the model saw and why that
matters; `verify_note` already distinguished `not_stated_possibly_truncated`
from a plain `not_stated`.

**Journal boilerplate was quotable.** `PMC8056687` (a PRISMA editorial) had
eight of nine body sections as Acknowledgements, Funding, Competing
interests and similar. That text is real, so *"The authors declare that
they have no competing interests"* would verify — a true quote backing a
claim the paper never made. Back-matter sections are now dropped before the
model sees them.

**That is the third instance of the same failure, and it is worth naming
as a finding in its own right.** Screening: the model quoted the eligibility
criteria from the prompt (97.8% of all verification failures). Full text:
it could quote a table cell as though it were prose. Full text again: it
could quote a competing-interests statement as a limitation. Every one of
these *passes* the span verifier, because the sentence genuinely exists.

**The span verifier answers "is this sentence real?" It has never answered
"is this sentence relevant?", and it cannot.** That is a real boundary on
the mechanism RQ1 rests on, found empirically three times rather than
argued, and the fix in all three cases was the same: control what the model
is allowed to see, rather than trying to catch a bad quote afterwards.
Week 15's discussion should state this plainly — it is a more interesting
claim than "verification works", and it is the honest version.

427 tests passing. `scripts/inspect_fulltext.py` is what made all three
diagnosable: it prints body length, sections, tables, figures and the XML
tags actually present, so a thin record, a parser bug and a genuinely
table-free paper can be told apart instead of guessed at.

**9 October 2026 — query expansion built and measured, and it is not a
win.** The proposal's Figure 2 promised "LLM turns the question into search
terms"; the artefact searched with whatever the user typed. `expand.py` now
asks the model for synonyms and technical equivalents, filters out search
syntax, phrases longer than six words, duplicates and anything the question
already says, and appends what is left. A failure of any kind returns the
question unchanged: expansion improves a search, it is never a precondition
for one.

**It is the one model stage with nothing to verify, and that is honest.**
Everywhere else the model makes a claim about a source and the claim is
withheld unless its quote is found there. Here it proposes words to search
with — there is no source to check them against. The check is empirical
instead: TNR@95 over each review's own corpus, with and without the terms.

| Review | criteria | +terms | title | +terms |
|---|---|---|---|---|
| Menon_2022 | 0.178 | 0.153 | 0.111 | **0.224** |
| Nelson_2002 | 0.038 | 0.035 | 0.280 | 0.238 |
| Radjenovic_2013 | 0.402 | **0.601** | 0.525 | **0.647** |
| Smid_2020 | 0.520 | 0.483 | 0.466 | 0.469 |
| van_der_Valk_2021 | 0.049 | 0.035 | 0.192 | 0.119 |
| van_der_Waal_2022 | 0.197 | 0.179 | 0.267 | **0.368** |

From a short question it helps on three reviews and hurts on three (mean
+0.037); from the full criteria text it helps on one and hurts on four. The
one large gain is Radjenovic_2013, the software-engineering review, where
"software defect prediction" and "metrics evaluation" are the field's own
words for what the criteria describe. On the medical reviews the terms
broaden into neighbouring topics and cost more than they find. **So it ships
off by default, as an offer with its terms shown** — n=6 makes this an
observation, not a finding, and a feature that helps half the time must not
be applied silently.

**A second result, which matters more for the product.** The obvious
experiment — search OpenAlex with and without the terms and count known
includes retrieved — cannot be run at any budget here. Searching with each
review's own title and taking the top 100 results with abstracts returned
**0 of 80** known includes for Nelson_2002, **0 of 48** for
Radjenovic_2013 and **1 of 27** for Smid_2020. Relevance ranking over 250
million works does not reproduce a systematic review's candidate set. Run a
Review is a screening demonstration over live literature, not a way to
rebuild a systematic review's search, and week 15 should say so plainly.

**A third, free observation.** The BM25 baseline queries with the full
criteria text, and on four of six reviews the review's own *title* ranks
better (Nelson_2002 0.038 -> 0.280, van_der_Valk_2021 0.049 -> 0.192). The
lexical baseline the dense arms were compared against may be understated by
its own query, which would narrow week 9's margins. Worth a sentence in
limitations, and worth re-running baseline_bm25 with a short query before
anyone cites those margins as a result.

`runs/20261008T153931706747Z-expand-29d4a7dc7a`, 496 tests passing.

## Next: close out week 11, run the week 12 usability check, submit ethics

Immediate: minute the week 11 go/no-go decision with the supervisor using
the precision and recall figures above, and find someone other than the
author to sit down with Search & Screen and complete a query unassisted.
Both need a real person, not more code, and neither can be done from here.

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

Spend to date: $0 (baselines, mock runs, and the week 8 Ollama run — local
GPU inference doesn't touch this budget at all).

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

**Default model is gemini-2.5-flash-lite** in config, though it is currently
blocked for this account (404, "no longer available to new users") — see 18
September note above. gemini-2.0-flash was shut down on 1 June 2026. Check
the deprecations page before any reported run.

**Local inference goes through Ollama, not llama-cpp-python.** No new pinned
dependency (`OllamaProvider` reuses `httpx`, already pinned); GPU offload is
automatic; and Ollama's `format` JSON-schema parameter gives the same
constrained-output guarantee `GeminiProvider` relies on, so parse-failure
rates stay comparable across providers instead of being confounded by one
having weaker JSON discipline. `llama-cpp-python`'s CUDA wheels on Windows
need a toolkit-matched build — real risk against 12h/week. Local inference is
$0 marginal cost by construction and does not count against the $50 budget;
it is a separate RQ2 arm, not a replacement for the Gemini figures.

**ASReview is run as an external tool**, not reimplemented. Removes an
implementation risk and a claim that would otherwise need defending.

**Flat FAISS index, not IVF.** 12,598 records is far too small for an
approximate index to be worth the accuracy loss.

**Rerank top 200 only.** Reranking everything is slow and pointless.

**RRF constant k=60, untuned.** No budget to justify a tuned value.

**The venv is Python 3.13, not the documented 3.11.** Discovered week 9
installing `faiss-cpu` (`1.9.0`, the original pin, has no 3.13 wheel — 3.11
isn't installed anywhere on this machine, and never has been on this venv;
`numpy` had already silently drifted off its own pin for the same reason
before this was caught). Decided to fix the pins and the `requirements.txt`
header to match what's actually running rather than force a disruptive
reinstall onto a Python version nothing here has ever used.

**SPECTER2 embeddings go through the `adapters` library's proximity
adapter, not plain `sentence-transformers`.** `allenai/specter2_base` alone
gives generic base embeddings; `AutoAdapterModel` + `load_adapter
("allenai/specter2", load_as="proximity", set_active=True)` is what makes
them retrieval-tuned. The library prints a misleading "none activated"
warning during loading — verified directly that the adapter is genuinely
active (embeddings with vs. without it differ, max abs diff 0.80) rather
than trusting or dismissing that warning either way.

---

## Running it

```bash
.venv\Scripts\activate
pytest -q
python -m slr.services.ingest --config configs/baseline_random.yaml
python -m slr.eval.harness --config configs/baseline_random.yaml --require-clean
python -m slr.eval.harness --config configs/baseline_bm25.yaml --require-clean
python -m slr.eval.harness --config configs/smoke.yaml --require-clean
python -m slr.eval.harness --config configs/week08_ollama.yaml --require-clean
python -m slr.eval.harness --config configs/week09_baseline_bm25.yaml --require-clean
python -m slr.eval.harness --config configs/week09_dense.yaml --require-clean
python -m slr.eval.harness --config configs/week09_hybrid.yaml --require-clean
python -m slr.eval.harness --config configs/week09_rerank.yaml --require-clean
python -m slr.eval.report_tables --runs runs --out reports
uvicorn slr.api.app:app              # dashboard backend, localhost:8000
streamlit run app/Home.py            # dashboard, localhost:8501 -- needs the API running
```

The dashboard reads whatever is already in `data/slr.db` and `runs/` — it
needs at least one review ingested and screened to show anything, and the
Search & Screen panel's live-screen button needs Ollama running the same
way `week08_ollama.yaml` does.

The first ingest downloads SYNERGY v1.0 (≈ 450 MB) to
`~/.synergy_dataset_source` and the criteria file to `data/synergy/`.
`configs/smoke.yaml` uses `provider: mock` — free, no API key, no network.
`configs/week08_ollama.yaml` needs Ollama running locally
(`ollama pull qwen2.5:7b-instruct`, then the default `localhost:11434` server)
— also free, no API key, but not network-free: it needs the local GPU.
`configs/week09_*.yaml` need no API key or Ollama — SPECTER2/MiniLM run
locally via `transformers`/`sentence-transformers`, CPU-only here (no CUDA
wheel installed). The first `dense`/`hybrid`/`rerank` run per review computes
and caches embeddings to `data/embeddings/` (~20 min for all three reviews
from cold); reruns are fast, served from that cache.

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
