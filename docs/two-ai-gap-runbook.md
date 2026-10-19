# Two-AI gap discovery — what to run

The supervisor asked that gap detection be cross-checked by two AIs. The
existing arm is `qwen2.5:7b-instruct` (local, $0). This adds a Gemini arm and
an OpenAI arm over the **same records from the same source runs**, so the only
thing differing between arms is the model.

Everything below runs on your machine.

**Start with Gemini alone.** You already have a working `GEMINI_API_KEY`, and
Gemini plus the existing local Qwen arm is already two AIs from two vendors —
which is what was asked for. On Gemini's free tier the whole arm may cost
nothing; on paid billing it is $0.16–0.23. OpenAI is a *third* arm and the only
piece needing a purchase ($5 minimum balance to spend about 4 cents), so it is
split into its own section at the end and can wait.

---

## 0. Before anything

```bash
git check-ignore -v .env          # must print a match. If it doesn't, STOP.
```

`GEMINI_API_KEY` is already set, so nothing is needed for the Gemini arm.
(`OPENAI_API_KEY` is only for the optional third arm in section 5.) A key goes
in `.env` — never in a config, a commit, or a chat window.

Then, because every reported run needs a clean tree (rule 3):

```bash
.venv\Scripts\activate
pytest -q                          # expect 519 passing
git status --short                 # expect empty
```

## 1. Five records first

The project's own debugging rule is `max_records` while developing. These cost
about $0.001 each and exist so a surprise — a wrong model name, a changed
price, reasoning tokens billed as output — is found here rather than 418
records in.

```bash
python -m slr.eval.gap_harness --config configs/gap_gemini_smoke.yaml --require-clean
```

**Check before going further:** open each new `runs/<ts>-gap-<hash>/run.json`
and compare `cost_usd` and `tokens_out` against the estimate in the config
header. If output tokens are far above ~113 per record, something is emitting
reasoning tokens and the full arm will cost several times its estimate — stop
and re-cost rather than running on.

## 2. The six reviews — smallest first

**The order matters on a free tier.** `harness.py` commits its SQLite
transaction only once a review's whole loop finishes (the 21 September
correction in `CLAUDE.md`), so a rate-limit abort mid-review discards that
review's progress — not the others, since each review is its own run. Running
smallest-first means you learn whether the free tier's quota is survivable on a
9-record review rather than a 132-record one.

Smid 9 records, Valk 11, Menon 69, van der Waal 82, Nelson 114,
Radjenović 132 — 417 in total.

```powershell
foreach ($r in "smid2020","valk2021","menon2022","vanderwaal2022","nelson2002","radjenovic2013") {
  python -m slr.eval.gap_harness --config "configs/gap_gemini_$r.yaml" --require-clean
}
```

bash:

```bash
for r in smid2020 valk2021 menon2022 vanderwaal2022 nelson2002 radjenovic2013; do
  python -m slr.eval.gap_harness --config configs/gap_gemini_$r.yaml --require-clean
done
```

`ceiling_usd` aborts the run if it is reached; it does not warn. The configs
already retry with exponential backoff, which absorbs ordinary 429s.

**If you are on the free tier, `cost_usd` in `run.json` is notional** — the
configs carry Gemini's real list price, so the number records what the arm
*would* have cost, not what was charged. That is useful for RQ2's cost
comparison, but the report has to say which it is.

## 3. Rate the new flags, blind

Each arm writes `gap_statements.jsonl`. The new flags need the same rating pass
the original 74 got — against the actual abstracts, under the rule fixed in
advance (the abstract states, in the authors' own words, that something is
unknown, unstudied, a limitation, or needs further research; bare
announcements and practice/policy recommendations do not count).

Rate them **before** looking at what the other arms said, or the agreement
figure is contaminated by your knowing where the models already disagree.

## 4. Agreement and the two combinations

Two arms is enough for the agreement figure; add the third only if you run it.

```bash
python -m slr.eval.gap_consensus --runs runs \
  --arm qwen2.5:7b-instruct=20260923T102642236622Z-gap-3496ae576f \
  --arm gemini-3.5-flash-lite=<new gemini run id>
```

With two arms you also get PABAK beside AC1, which three arms cannot give.

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

## 5. The optional third arm: OpenAI

Only worth doing if your supervisor wants ChatGPT specifically by name. It
needs a prepaid balance (USD 5 minimum) to spend roughly 4 cents, and it adds
nothing the Gemini arm does not already provide for the "two AIs" requirement.

1. `platform.openai.com` → Settings → Billing → add a payment method and buy
   credit. **Turn auto-reload off**, and set a low monthly usage limit, so $5
   is the real maximum exposure.
2. Settings → API keys → create one. It is shown once. Put it in `.env` as
   `OPENAI_API_KEY=` and nowhere else.
3. `python -m slr.eval.gap_harness --config configs/gap_openai_smoke.yaml --require-clean`
4. Check `run.json` for runaway `tokens_out` before the six full runs, then the
   same smallest-first loop with `gap_openai_$r.yaml`.
5. Re-run `gap_consensus` with all three `--arm` flags.

`OpenAIProvider` and all six configs are already built, tested and committed —
nothing needs writing when you decide to do this.

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

---
