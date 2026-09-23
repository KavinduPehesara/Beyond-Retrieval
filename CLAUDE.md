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

## Current state — week 11 of 15

Done: literature review, proposal (submitted), architecture, scope lock, the
walking skeleton, the week 8 evaluation harness, the first baseline runs on
real SYNERGY data, the first model recall figures (local Ollama), week 9's
dense retrieval (SPECTER2 + FAISS, RRF fusion, cross-encoder rerank), week
10's prompt variants, model tier comparison, the overridable mechanism, and
genuine inter-run reproducibility, and week 11's gap-discovery mechanism
with 21 rated statements (90.5% precision) — go/no-go decision not yet
minuted with the supervisor (see below). Weeks 8, 9 and 10 exit tests
passed; week 11's is open pending that decision. Also done, outside the
original schedule: a structured
data-extraction feature and report, added at the supervisor's request (see
21 September note below).

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
  adapters/
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
    inter_run.py          genuine inter-run Gwet AC1 across repeated runs
    report_tables.py     run directories -> reports/results.{csv,md}
prompts/screen_v1.txt    prompt template, versioned by filename
prompts/screen_v2.txt    step-by-step + one-sentence reasoning (week 10, underperformed v1)
prompts/screen_v3.txt    terse, minimal rules (week 10, underperformed v1)
prompts/extract_v1.txt   extraction prompt: 4 fields, each with a quote or "not_stated"
prompts/gap_v1.txt       gap-discovery prompt: 1 field, "gap_stated" or "not_stated"
configs/smoke.yaml       Nelson_2002, 50 records, mock provider, free
configs/baseline_*.yaml  random and BM25 over Smid_2020 + Nelson_2002, free
configs/week08_gemini.yaml  Smid_2020 + Nelson_2002, gemini-2.5-flash-lite (blocked, see below)
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
data/embeddings/         SPECTER2 vectors cached per review (gitignored)
tests/                   166 tests
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

- Never run against the real Gemini API for a reported figure — the 404
  above blocked it; `configs/week08_gemini.yaml` needs a price/ceiling update
  (currently priced for the now-blocked model) before it is run for real.
- Smid_2020, Nelson_2002, van_der_Valk_2021 and Radjenovic_2013 are ingested
  and fully screened. The other two (van_der_Waal_2022, Menon_2022) load
  with the same ingest command once added to a config.
- Ethics application for the usability study — not submitted. This is the only
  item whose timing is outside the author's control. It gates week 13. (The
  proposal, section 8.2, says approval is obtained in week 7.)

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

**The honest shortfall (rule 7): 21 rated, not 30.** The full pool of
currently-screened verified-includes across all four ingested reviews is
267 records; only 21 of them (7.9%) state an explicit gap at all — the
low base rate, not a discovery failure, is why the sample fell short of
the plan's 30. Two ways to close the gap, not yet decided: (a) ingest and
screen the two remaining SYNERGY reviews (`van_der_Waal_2022`,
`Menon_2022`) to grow the candidate pool, or (b) run gap discovery over
verified-excludes too, since a gap statement's presence in an abstract
doesn't depend on whether that abstract happened to meet one review's
inclusion criteria. Neither is done yet.

**Go/no-go: data points to go, decision not yet minuted.** Both precision
figures (90.5% literal, 71.4% actionable) are comfortably above any
threshold that would trigger the prior-art-retrieval fallback the schedule
names — but the checkpoint's own text calls for a decision minuted with
the supervisor, on 30 statements, and this is 21. Recorded here as the
evidence to bring to that conversation, not as a decision made
unilaterally on its behalf.

Run directories: `runs/20260923T102642236622Z-gap-3496ae576f` (Nelson_2002),
`.../20260923T102816243601Z-gap-80a180d02a` (Smid_2020),
`.../20260923T102825404365Z-gap-8002013514` (van_der_Valk_2021),
`.../20260923T102838078110Z-gap-c8a03baad8` (Radjenovic_2013), each with
its own `gap_ratings.json`.

## Next: close out week 11, then week 12 — FastAPI + Streamlit panels

Immediate: decide (a) vs (b) above to reach 30 rated statements, and
minute the go/no-go decision with the supervisor using the numbers above.
Week 12 exit test, once week 11 is closed: someone other than the author
completes a query unassisted.

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
```

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
