# Demonstrating Beyond Retrieval

Written for the week 14 presentation. The point of a rehearsal is not
practice; it is that the rehearsal leaves the cache warm and the project
saved, so the live run has almost nothing left to fail at.

## Thirty minutes before

```bash
ollama serve                              # the fallback model, if not already up
uvicorn slr.api.app:app                   # backend, 8000
streamlit run app/Home.py                 # the app, 8501
python scripts/preflight.py --paid        # proves each one answers
```

`--paid` makes one real call per provider, a fraction of a cent. It is the
only check that distinguishes *configured* from *working*: an expired key
and a valid one look identical until something calls them.

Every line must read `ok`, except ChatGPT if no `OPENAI_API_KEY` is set —
that one reads `warn` and the app shows it greyed out with the reason.

## The rehearsal, which is also the safety net

1. Sign in with Google, create a project (e.g. "Probiotics and IBS").
2. Pick **Gemini**, ask the question you will ask on stage, 20 papers.
3. Let it finish, then pick two papers and read them in full.

This does three things: it warms the response cache, so the same question
on stage returns in about half the time; it saves the search *and* the
full-text results into the project; and it tells you the actual numbers
you will see, so nothing on screen surprises you.

**If the venue's network fails, open the saved project instead of asking
the question.** A saved search renders from the database with no calls to
OpenAlex, Europe PMC or any model. The screen looks identical.

## The five beats

| Beat | What to say |
|---|---|
| The question | Plain language, no eligibility criteria. The question itself becomes the inclusion rule. |
| Suggested papers | Each verdict carries the sentence it rests on, found word for word in the abstract. A verdict whose quote cannot be found is withheld, not shown with a confidence score. |
| Is it an open gap? | The gaps other authors state, in their own words, ranked by closeness to the question. |
| Full text | The gaps a paper states in its own body, quoted and placed in its section — invisible to the abstract stage. Tables come from the publisher's own markup, not inferred from prose. |
| Which AI | The same records can go to a second vendor. Agreement between them measures consistency, not correctness. |

## Numbers worth having ready

- 12,598 records across six reviews, 0.8%–21.9% inclusion, reported per review, never pooled.
- Verification rate 35.6%–94.8%; the model almost never invents a quotation (12 times in 5,909 failures) — it answers a different question.
- Gap suggestion: 87.8% precision over 74 rated statements; blind-sampled recall 0.40–1.00, intervals wide.
- Calibration: mean confidence 0.813 where the quote verified, 0.798 where it did not, across 23,148 decisions. That gap is why a confidence score would mislead and an unsubstantiated decision is withheld.
- Latency measured here: Gemini 1.3s a call, the local model 9.7s. Twenty papers is about half a minute against a hosted model.
- 521 tests pass.

## If it goes wrong on stage

| Symptom | Do this |
|---|---|
| "No results had an abstract to check" | OpenAlex hiccup. Open the saved project rather than retrying. |
| The model times out | Switch provider in the form and ask again; the other one is already configured. |
| Full text unavailable for a paper | That is the honest path working: Europe PMC holds only the open-access subset, and the app says which paper and why. Say so. |
| Sign-in fails on the venue network | Demonstrate as a guest. Search, screening and gap suggestion all work; only full text and saved projects need an account. |
