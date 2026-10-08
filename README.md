# Beyond Retrieval

An LLM-supported dashboard for literature review and research gap detection.

Every screening decision the system makes carries a verbatim quote from the
paper it came from, and that quote is checked against the source before the
decision is allowed into the result set. Decisions that cannot be verified are
routed to a human. The system also extracts the limitations and future work
authors state in their own papers, clusters them, and shows where a field is
thin.

MSE907 Industry-based Capstone Research Project  
Master of Software Engineering (Level 9)  
Pehesara Gunawardena · 270684416

---

## Why this exists

Two problems sit behind this project.

A public dataset built from 26 real systematic reviews holds 169,288 papers, of
which 1.67% were kept — roughly fifty-nine irrelevant papers read for every
useful one. Language models can reduce that burden, but the evidence is
contested: Khraisha et al. (2024) recorded sensitivity of 0.42 on balanced data,
and Hida et al. (2026) found accuracy differences of up to 47 percentage points
between models, with decisions changing between identical runs at temperature
zero.

Meanwhile only four of twenty-one surveyed review tools are open source
(Bolaños et al., 2024), and commercial providers withhold their evaluation data,
so a researcher cannot determine the recall of the tool they rely on. None of
the thirty-four features those authors assessed concerns identifying what a
literature does *not* contain.

This repository is the artefact answering both.

---

## Research questions

**RQ1 — Trustworthiness.** Can an LLM-supported literature review tool produce
screening decisions that a researcher can independently verify and rely on?

Trust is treated as four measurable properties, each enforced by a mechanism in
the code rather than assessed after the fact:

| Property | Enforced by |
|---|---|
| Verifiable | A response is rejected unless its quote is found verbatim in the source |
| Accurate | The evaluation harness measures every configuration against recorded human decisions before it is adopted |
| Reproducible | Response cache keyed on model, prompt version and record, refusing any hit whose request differs; seed sent to the provider; inter-run agreement (Gwet's AC1) measured, not assumed |
| Overridable | The system proposes, the reviewer disposes; overrides kept as labelled data |

**RQ2 — Fast, accurate knowledge discovery.** How much reviewing effort, time
and monetary cost does the system remove at a fixed level of recall, and can it
surface the research gaps authors state in their own papers?

---

## Status

Week 12 of 15 (hardening into week 13). All six reviews are ingested and
screened; dense/hybrid/rerank retrieval, prompt and model-tier comparisons,
the overridable mechanism, gap discovery, data extraction, a FastAPI backend
and a 5-panel Streamlit dashboard are all built and verified against real
data. Full detail, every run directory, and every negative result: `CLAUDE.md`.

| Weeks | Deliverable | State |
|---|---|---|
| 1–6 | Literature review, proposal, architecture, scope lock | Done |
| 7–8 | Walking skeleton, then the evaluation harness | Passed |
| 9 | Dense retrieval (SPECTER2, FAISS, RRF fusion, reranking) | Passed |
| 10 | Prompt variants, model tiers, overridable mechanism, agreement | Passed |
| 11 | Gap discovery | Built, numbers ready (87.8% precision); go/no-go not yet minuted with the supervisor |
| 12 | FastAPI backend, 5 Streamlit panels | Built and verified end-to-end; usability exit test (a second person, unassisted) not yet run |
| 13 | Usability evaluation, hardening, reproduction script | In progress — ethics application for the human study not yet submitted |
| 14–15 | Final baselines, ASReview comparison, report, submission | Not started |

Current numbers for every review (prevalence, verification rate, recall,
reproducibility, gap precision/recall) live in `CLAUDE.md` and
[`reports/results.md`](reports/results.md), generated from `runs/` rather
than retyped here — a number copied into this file would go stale the next
time a run updates it.

---

## Quick start

Requires Python 3.13 (the pinned versions in `requirements.txt` target it —
see `SETUP.md` for the full, step-by-step first-time setup, including the
public-repository secrets checklist).

```bash
git clone https://github.com/KavinduPehesara/Beyond-Retrieval.git
cd Beyond-Retrieval

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
pytest -q
```

Load the corpus — all six evaluation-subset reviews in one command. The
first run downloads the SYNERGY v1.0 release (about 450 MB, to
`~/.synergy_dataset_source`, outside the repository) and the published
eligibility criteria from a pinned commit:

```bash
python -m slr.services.ingest --config configs/ingest_all.yaml
```

Run the baselines (no model calls, no cost) and the smoke test (mock provider,
no key, no cost). Commit first; `--require-clean` refuses to run otherwise:

```bash
python -m slr.eval.harness --config configs/baseline_random.yaml --require-clean
python -m slr.eval.harness --config configs/baseline_bm25.yaml --require-clean
python -m slr.eval.harness --config configs/smoke.yaml --require-clean
```

Screen for real, at $0, with a local model — install
[Ollama](https://ollama.com), pull `qwen2.5:7b-instruct`, then:

```bash
python -m slr.eval.harness --config configs/week08_ollama.yaml --require-clean
```

Screening with Gemini instead is supported (`provider: gemini` in a config)
but costs real money against this project's $50 ceiling and needs
`GEMINI_API_KEY` in `.env` — see `SETUP.md` section 3 before adding one to a
clone of a public repository.

Build the report tables from every run directory:

```bash
python -m slr.eval.report_tables --runs runs --out reports
```

Bring up the dashboard (needs at least one review ingested and screened):

```bash
uvicorn slr.api.app:app              # backend, localhost:8000
streamlit run app/Home.py            # dashboard, localhost:8501 -- needs the API running
```

Each run writes `runs/<timestamp>-<config-hash>/`:

| File | Holds | Committed |
|---|---|---|
| `config.yaml` | the config exactly as written | yes |
| `resolved_config.json` | the config with defaults applied | yes |
| `metrics.json` | results only — identical for two runs of the same config | yes |
| `run.json` | this execution: commit, timings, live spend, cache hits | yes |
| `git_sha.txt` | the commit the code was at | yes |
| `responses.jsonl` | every decision, with quoted abstract text | no |

---

## Live research workspace

Live searches are saved separately in `data/live_reviews.sqlite3`, outside the
benchmark corpus. Sign in, create a named project and use **My research projects**
to reopen results. Each paper's **Researcher review** panel records an include,
exclude or pending decision, a rationale, and optional technique/domain coding.
Edits append to the audit trail; original model outputs remain unchanged.
Researcher include/exclude decisions control the full-text selection list.
Changing a decision does not automatically rerun abstract extraction.

The optional **Semantic map** uses SPECTER2 proximity embeddings of titles and
abstracts, normalized and projected with PCA. It requires at least three
abstracts and a working local embedding model; the first build can be slow.
Maps are cached per saved session. Distances are exploratory and do not measure
relevance, quality or research absence.

The **Gap coverage matrix** counts reviewer-coded technique/domain combinations.
Both labels require a source quote matching the stored abstract. Select a cell
to inspect its papers and verified author-stated gap quotes. Excluded papers
are omitted; pending coded papers remain provisional. Categories are assigned
by the reviewer, not automatically inferred. Empty cells only describe this
small retrieved set and cannot establish that research is missing. Export the
saved review, current decisions, matrix and append-only audit trail as JSON.

## Full-text source coverage

After **Read these in full**, each paper has eight source categories: data
tables, heat maps, graphs/charts, statistical results, methods,
equations/models, supplementary files, and limitations. Every category
reports what was retrieved or why it is unavailable. Table CSV and source
evidence JSON downloads retain provenance; footnotes and merged-cell
positions are preserved. Equation LaTeX is rendered where supplied, with
original MathML available to download.

Additional methods, statistics, model and limitations passages are selected
by headings/keywords from the complete retrieved prose, independently of
the capped model prompt. They are exact source passages for human review,
not a claim of complete semantic extraction. The five existing model fields
still require a source-matching quote; their historical prompt and results
are unchanged.

Figure images and supplementary files come from Europe PMC's
[public asset archive](https://europepmc.org/RestfulWebService).
Images are displayed when available; heat-map classification uses captions.
Pixel interpretation, chart digitization and OCR are not implemented.
Supplement previews support text, CSV/TSV, XML/JSON, DOCX, XLSX and text-based
PDF. Unsupported files remain downloadable. Source restrictions, empty
files and missing assets are reported explicitly. Downloads and previews
are bounded and cached under the gitignored `data/fulltext_assets/`.

The HTTP API requests assets only with `include_assets: true` on
`POST /discover/fulltext`; the dashboard enables this by default. No paid
model or external vision service is used.

## Evaluation corpus

Six reviews from the SYNERGY benchmark, chosen so inclusion rates span 0.8% to
21.9%. Varying prevalence deliberately is a stronger test than a larger corpus
that does not, because screening accuracy is known to inflate on balanced data.
Radjenović_2013 is a software engineering review; Smid_2020 reviews
statistical methodology.

| Review | Domain | Records | Included |
|---|---|---|---|
| Radjenović_2013 | Software engineering | 5,935 | 48 (0.8%) |
| Smid_2020 | Computer science | 2,627 | 27 (1.0%) |
| van_der_Waal_2022 | Medicine | 1,970 | 33 (1.7%) |
| Menon_2022 | Medicine | 975 | 74 (7.6%) |
| van_der_Valk_2021 | Medicine, psychology | 725 | 89 (12.3%) |
| Nelson_2002 | Medicine | 366 | 80 (21.9%) |
| **Total** | | **12,598** | **351 (2.8%)** |

Results are reported per review, never pooled, each figure carrying the class
balance that produced it.

---

## Rules this repository follows

1. Nothing is optimised before the evaluation harness exists.
2. Every reported number comes from a run directory containing its config and
   commit hash. If it only exists in a terminal, it does not exist.
3. Commit before every run. The git SHA goes into the run artefact, and
   `--require-clean` enforces it.
4. Ground truth is never in the prompt. `label_included` is read by the metrics
   module and by nothing else.
5. Results are reported per review, always with the inclusion rate beside them.
6. A failed exit test cuts scope; it does not extend the week.
7. A negative result is a result, written down the day it is observed.

---

## Costs

Screening the full 169,288-record benchmark once costs roughly USD 25 at
low-tier model prices, and the experimental design needs about twenty passes.
That is why the corpus is a subset. The budget ceiling is set in
`configs/*.yaml` and aborts the run rather than warning.

---

## Data and licensing

Bibliographic records come from the [OpenAlex API](https://openalex.org)
(CC0). Ground-truth screening labels and eligibility criteria come from the
[SYNERGY dataset](https://github.com/asreview/synergy-dataset) published by the
ASReview project. Neither is redistributed here; both are fetched by script.
SYNERGY asks that abstracts not be republished as plain text, so the database
and raw responses are gitignored.

Code in this repository is released under the MIT License. See `LICENSE`.

---

## Citing

> Gunawardena, P. (2026). *Beyond Retrieval: An LLM-Supported Dashboard for
> Literature Review and Research Gap Detection.* Capstone project, Master of
> Software Engineering, MSE907.

---

## Key references

- Bolaños, F., Salatino, A., Osborne, F., & Motta, E. (2024). Artificial intelligence for literature reviews: Opportunities and challenges. *Artificial Intelligence Review, 57*(10), 259.
- De Bruin, J., Ma, Y., Ferdinands, G., Teijema, J., & Van de Schoot, R. (2023). *SYNERGY — Open machine learning dataset on study selection in systematic reviews.* DataverseNL.
- Gwet, K. L. (2014). *Handbook of inter-rater reliability* (4th ed.). Advanced Analytics.
- Hida, G. S., Ribeiro, D. M., & Yahata, E. (2026). Beyond accuracy: LLM variability in evidence screening for software engineering SLRs. *arXiv preprint* arXiv:2604.27006.
- Khraisha, Q., et al. (2024). Can large language models replace humans in systematic reviews? *Research Synthesis Methods, 15*(4), 616–626.
- Kusa, W., Lipani, A., Knoth, P., & Hanbury, A. (2023). An analysis of work saved over sampling in the evaluation of automated citation screening. *Intelligent Systems with Applications, 18*, 200193.
- Zhang, C., et al. (2023). Automatic recognition and classification of future work sentences. *Journal of Informetrics, 17*(1), 101373.

### Google accounts

Saved live reviews now belong to the signed-in Google account. Review IDs are no longer shown in the page; reopen reviews from **My research projects**. Guest searches remain available without saving. Configure Google OAuth using [the setup guide](docs/google-sign-in.md).


### Named research projects

The home page starts with Google login or **Skip and continue to home**. Guests can search and screen abstracts. Sign in and create a named project before saving research or retrieving full text. The API enforces account ownership and the full-text login requirement.

Create, open, rename and remove projects from **My research projects**. Search results, criteria, reviewer decisions, full-text results and coverage evidence are saved locally in the account-owned project. Additional full-text requests retain papers retrieved earlier. Re-running a search preserves the previous results and full text in downloadable search-history snapshots. Remove archives the project locally and hides it from the library; it does not permanently erase it. Only submitted searches and saved reviewer decisions are persisted, not unsubmitted form edits or unsaved paper selections.
