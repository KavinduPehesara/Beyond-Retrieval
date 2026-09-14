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

Week 8 of 15. The evaluation harness runs on real SYNERGY data and reproduces
its metrics files exactly; the first screening run with a real model is next.

| Weeks | Deliverable | State |
|---|---|---|
| 1–6 | Literature review, proposal, architecture, scope lock | Done |
| 7–8 | Walking skeleton, then the evaluation harness | Harness reproducible on real data; first model recall figures pending |
| 9–10 | Retrieval and screening quality | |
| 11 | Gap discovery; go / no-go checkpoint | |
| 12–13 | Dashboard panels; usability evaluation | |
| 14–15 | Final runs, analysis, submission | |

### First numbers — baselines

Every record of each review ranked; true negative rate and work saved over
sampling at 95% recall. BM25 queries are each review's published eligibility
criteria. Full tables: [`reports/results.md`](reports/results.md).

| Review | Records | Prevalence | Random TNR@95 | BM25 TNR@95 | BM25 WSS@95 |
|---|---|---|---|---|---|
| Smid_2020 | 2,627 | 1.0% | 0.029 | 0.568 | 0.513 |
| Nelson_2002 | 366 | 21.9% | 0.066 | 0.080 | 0.024 |

Random is a single seed (42). Both configurations reproduced byte-identical
metrics files on a second run.

---

## Quick start

Requires Python 3.11 (the pinned versions in `requirements.txt` target it).

```bash
git clone https://github.com/KavinduPehesara/Beyond-Retrieval.git
cd Beyond-Retrieval

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
pytest -q
```

Load the corpus. The first ingest downloads the SYNERGY v1.0 release (about
450 MB, to `~/.synergy_dataset_source`, outside the repository) and the
published eligibility criteria from a pinned commit:

```bash
python -m slr.services.ingest --config configs/baseline_random.yaml
```

Run the baselines (no model calls, no cost) and the smoke test (mock provider,
no key, no cost). Commit first; `--require-clean` refuses to run otherwise:

```bash
python -m slr.eval.harness --config configs/baseline_random.yaml --require-clean
python -m slr.eval.harness --config configs/baseline_bm25.yaml --require-clean
python -m slr.eval.harness --config configs/smoke.yaml --require-clean
```

Screen with Gemini — add `GEMINI_API_KEY` to `.env` first, after checking
`git check-ignore -v .env`:

```bash
copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux
python -m slr.eval.harness --config configs/week08_gemini.yaml --require-clean
```

Build the report tables from every run directory:

```bash
python -m slr.eval.report_tables --runs runs --out reports
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
