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
| Reproducible | Response caching keyed on model, prompt version and record; fixed seeds; repeated-run design |
| Overridable | The system proposes, the reviewer disposes; overrides kept as labelled data |

**RQ2 — Fast, accurate knowledge discovery.** How much reviewing effort, time
and monetary cost does the system remove at a fixed level of recall, and can it
surface the research gaps authors state in their own papers?

---

## Status

Week 7 of 15. Building the walking skeleton.

| Weeks | Deliverable | State |
|---|---|---|
| 1–6 | Literature review, proposal, architecture, scope lock | Done |
| 7–8 | Walking skeleton, then the evaluation harness | In progress |
| 9–10 | Retrieval and screening quality | |
| 11 | Gap discovery; go / no-go checkpoint | |
| 12–13 | Dashboard panels; usability evaluation | |
| 14–15 | Final runs, analysis, submission | |

---

## Quick start

Requires Python 3.11.

```bash
git clone https://github.com/KavinduPehesara/Beyond-Retrieval.git
cd Beyond-Retrieval

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt

copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux
# then open .env and add your API key
```

Fetch the benchmark corpus:

```bash
python -m synergy_dataset get
python -m slr.services.ingest --config configs/smoke.yaml
```

Run the pipeline:

```bash
python -m slr.eval.harness --config configs/smoke.yaml
```

Results land in `runs/<timestamp>-<config-hash>/`, containing the config that
produced them, the metrics, and the commit hash of the code that ran.

---

## Evaluation corpus

Six reviews from the SYNERGY benchmark, chosen so inclusion rates span 0.8% to
21.9%. Varying prevalence deliberately is a stronger test than a larger corpus
that does not, because screening accuracy is known to inflate on balanced data.
Two of the six are software engineering reviews.

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
3. Commit before every run. The git SHA goes into the run artefact.
4. Ground truth is never in the prompt. `label_included` is read by the metrics
   module and by nothing else.
5. Results are reported per review, always with the inclusion rate beside them.
6. A failed exit test cuts scope; it does not extend the week.
7. A negative result is a result, written down the day it is observed.

---

## Costs

Screening the full 169,288-record benchmark once costs roughly USD 25 at
low-tier model prices, and the experimental design needs about twenty passes.
That is why the corpus is a subset. The budget ceiling is enforced in
`configs/*.yaml` and aborts the run rather than warning.

---

## Data and licensing

Bibliographic records come from the [OpenAlex API](https://openalex.org)
(CC0). Ground-truth screening labels come from the
[SYNERGY dataset](https://github.com/asreview/synergy-dataset) published by the
ASReview project (CC0). Neither is redistributed here; both are fetched by
script.

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
- Khraisha, Q., et al. (2024). Can large language models replace humans in systematic reviews? *Research Synthesis Methods, 15*(4), 616–626.
- Kusa, W., Lipani, A., Knoth, P., & Hanbury, A. (2023). An analysis of work saved over sampling in the evaluation of automated citation screening. *Intelligent Systems with Applications, 18*, 200193.
- Zhang, C., et al. (2023). Automatic recognition and classification of future work sentences. *Journal of Informetrics, 17*(1), 101373.
