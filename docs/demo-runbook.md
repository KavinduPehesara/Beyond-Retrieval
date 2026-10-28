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

---

# Recording the demonstration video

PowerPoint records straight into a slide: **Insert → Screen Recording**, pick
the browser window, record, then right-click the video → Trim. No install, no
file to lose. Windows' own **Win + Alt + R** (Game Bar) is the fallback, and
writes an .mp4 to Videos/Captures.

Record at 1920×1080 if you can, with the browser at about 90% zoom so a whole
stage fits without scrolling mid-sentence.

## Before you press record

Run the rehearsal above. It warms the cache, so the search takes about half a
minute instead of several, and the papers you read are already extracted —
the recording shows the tool at its real speed, not waiting on a first run.
Then sign out (or open a private window) so the video starts at the front
door.

Close anything with your API keys on screen: `.env`, the terminal where you
started the servers, and your editor.

## The shot list — about three minutes

| Time | On screen | What to say |
|---|---|---|
| 0:00 | The welcome dialog, three cards | What the tool is for: find the papers, check every decision yourself. |
| 0:15 | Sign in, open the project | Signing in saves the work and unlocks full text. |
| 0:30 | Type the question, pick the AI | No eligibility criteria — the question itself becomes the inclusion rule. Name which AI is answering. |
| 0:40 | The progress bar moving | It says which paper of how many is being checked, because the model takes real time and a spinner tells you nothing. |
| 1:10 | The four counts, then the list | 50 ranked, 20 suggested, 12 addressing the question, N stating a gap. |
| 1:25 | One paper's "Why" quote | This sentence is in the paper, found word for word. If it could not be found, the verdict is withheld rather than shown with a confidence score. |
| 1:45 | "Is your question an open gap?" | Other authors saying, in their own words, that this is unstudied. |
| 2:00 | Tick two papers, Extract | The researcher decides what deserves a deeper read, not the model. |
| 2:10 | Reading progress, naming each paper | A lookup, a download and two long model calls per paper. |
| 2:30 | The full-text panel | The gaps this paper states in its own body, quoted and placed in its section — the abstract stage cannot see these. Tables come from the publisher's markup, not guessed from prose. |
| 2:45 | At a glance, then Download | Full text yes/no, gaps stated, and the whole session leaves as a folder you keep. |

## Say these two things somewhere

They are the project's argument, and a video without them is just a tour:

- **A decision whose quote cannot be found is withheld, not shown with a
  confidence score.** Mean model confidence was 0.813 where the quote
  verified and 0.798 where it did not, across 23,148 decisions — the model is
  as confident when it cannot substantiate an answer as when it can.
- **Verification proves a sentence is real, not that it is relevant.** That
  limit was found four times in this project, and each fix was the same:
  control what the model may quote.

## If a take goes wrong

Do not restart the servers mid-recording. Stop, run `python
scripts/preflight.py`, and start a new take from the front door. A cached
question reruns in well under a minute, so a retake is cheap.
