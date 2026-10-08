# Live research workspace verification — 9 October 2026

Implemented saved live review sessions, a separate append-only researcher audit
trail, SPECTER2/PCA maps for live search results, and a reviewer-coded technique
by domain coverage matrix linked to exact abstract evidence.

- Full regression suite: 460 passed, two dependency deprecation warnings.
- Final chart-selection compatibility check: two focused workspace tests passed.
- A real OpenAlex search returned five papers with stored abstracts. The saved
  review was reopened through the dashboard's resume form.
- The real SPECTER2 model generated 768-dimensional embeddings. The five-paper
  live map rendered successfully and retained approximately 70% of variation.
- An isolated session labelled TEST DEMO ONLY was used for three provisional
  coding actions. Its 2-by-2 matrix contained three populated cells and one
  empty cell; evidence passages and source links were displayed.
- Original model outputs remain unchanged. Live reviewer actions never enter
  the benchmark human-decision table. Researcher includes/excludes determine
  which papers can be selected for full-text retrieval.

These are functional checks, not accuracy or usability evaluation results.
Matrix categories are manually assigned and provisional demo actions are not
researcher judgements. Quote matching establishes source presence, not that the
quote justifies a label. Empty cells do not establish absence from the literature.
Changing a screening decision does not automatically rerun abstract extraction.
The new views do not fulfil every proposal target, including PRISMA, complete
metadata distributions, automated gap classification or the planned user study.
