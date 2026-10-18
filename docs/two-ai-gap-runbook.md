# Two-AI gap discovery — what to run

The supervisor asked that gap detection be cross-checked by two AIs. The
existing arm is `qwen2.5:7b-instruct` (local, $0). This adds a Gemini arm and
an OpenAI arm over the **same records from the same source runs**, so the only
thing differing between arms is the model.

Everything below runs on your machine. Total estimated spend: **$0.262**, plus
OpenAI's $5 minimum prepaid balance.

---

## 0. Before anything

```bash
git check-ignore -v .env          # must print a match. If it doesn't, STOP.
```

`GEMINI_API_KEY` is already set. Add `OPENAI_API_KEY` to `.env` — never to a
config, a commit, or a chat window. OpenAI has no free tier, so the account
needs a prepaid balance (USD 5 minimum) before the first call succeeds.

Then, because every reported run needs a clean tree (rule 3):

```bash
.venv\Scripts\activate
pytest -q                          # expect 519 passing
git status --short                 # expect empty
```

## 1. Five records first, each arm

The project's own debugging rule is `max_records` while developing. These cost
about $0.001 each and exist so a surprise — a wrong model name, a changed
price, reasoning tokens billed as output — is found here rather than 418
records in.

```bash
python -m slr.eval.gap_harness --config configs/gap_gemini_smoke.yaml --require-clean
python -m slr.eval.gap_harness --config configs/gap_openai_smoke.yaml --require-clean
```

**Check before going further:** open each new `runs/<ts>-gap-<hash>/run.json`
and compare `cost_usd` and `tokens_out` against the estimate in the config
header. If output tokens are far above ~113 per record, something is emitting
reasoning tokens and the full arm will cost several times its estimate — stop
and re-cost rather than running on.

## 2. The six reviews, each arm

Each writes its own run directory. `ceiling_usd` aborts the run if it is
reached; it does not warn.

```bash
for r in nelson2002 smid2020 valk2021 radjenovic2013 menon2022 vanderwaal2022; do
  python -m slr.eval.gap_harness --config configs/gap_gemini_$r.yaml --require-clean
done
```

PowerShell:

```powershell
foreach ($r in "nelson2002","smid2020","valk2021","radjenovic2013","menon2022","vanderwaal2022") {
  python -m slr.eval.gap_harness --config "configs/gap_gemini_$r.yaml" --require-clean
}
```

Then the same six with `gap_openai_$r.yaml`.

## 3. Rate the new flags, blind

Each arm writes `gap_statements.jsonl`. The new flags need the same rating pass
the original 74 got — against the actual abstracts, under the rule fixed in
advance (the abstract states, in the authors' own words, that something is
unknown, unstudied, a limitation, or needs further research; bare
announcements and practice/policy recommendations do not count).

Rate them **before** looking at what the other arms said, or the agreement
figure is contaminated by your knowing where the models already disagree.

## 4. Agreement and the two combinations

```bash
python -m slr.eval.gap_consensus --runs runs \
  --arm qwen2.5:7b-instruct=20260923T102642236622Z-gap-3496ae576f \
  --arm gemini-3.5-flash-lite=<new gemini run id> \
  --arm gpt-5-nano=<new openai run id>
```

Repeat per review, or pass the six-review runs; the tool reports per review and
never pools (rule 5). It writes `runs/<ts>-gapconsensus-<hash>/` with
`metrics.json`, `consensus.md` and `git_sha.txt`.

What comes out: per-review Gwet AC1 between the arms, PABAK when there are
exactly two, how many records every arm agreed on, and the two combination
policies — `both` (intersection: higher precision, lower recall) and `either`
(union: higher recall, lower precision). Your measured weakness is recall, so
`either` is the one likelier to help, but both are computed rather than
assumed. The listed disagreements are the records worth your time: they are
what a second rater actually buys.

---

## Two things to say in the report, not quietly assume

**Agreement is not correctness.** Two models agreeing can both be wrong, and
models with overlapping training data correlate in their errors, so this figure
reads higher than genuine independence would justify. It measures consistency.
Precision still comes from the human-rated reference set. The tool writes this
caveat into its own output so it cannot be dropped by accident.

**Gemini and OpenAI are not fully independent either.** They are different
vendors, which is better than two Qwen checkpoints, but both are large models
trained on overlapping web-scale corpora. "Two AIs" reduces single-model
idiosyncrasy; it does not give two genuinely independent observers in the sense
inter-rater reliability normally assumes.

## Known issue you will hit

`google-genai==0.3.0` is pinned and **yanked from PyPI** (Pillow CVE-2026-54058
and others). It still installs, with a warning. It was not bumped because the
API surface changed across two major versions and breaking the verified Gemini
path in the final week is the worse risk — but a fresh clone now installs a
withdrawn package, so week 13's fresh-clone exit test needs that caveat
attached. See the 18 October note in `CLAUDE.md`.
