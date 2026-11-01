# Beyond Retrieval — speaking script

**MSE907 Assessment 3** · Kavindu Pehesara Gunawardena · 270684416 · supervisor Dr Helena Bahrami

14 slides. Planned runtime **14:59**: about 2087 spoken words at 140 words per minute, plus a 1:45 demo recording on slide 7. Text in square brackets is a cue, not something you say. The same script is in the speaker notes of the .pptx, so presenter view shows it slide by slide.

If you run long, the first things to drop are the bracketed aside on slide 5 and the licensing sentence on slide 11. Slide 7 is your checkpoint: you should be starting the video at about 5:15.

## Running order

| # | Slide | From | To | Words |
|---|---|---|---|---|
| 1 | Beyond Retrieval | 0:00 | 0:28 | 67 |
| 2 | Two burdens — and only one is being worked on | 0:28 | 1:15 | 108 |
| 3 | Three published claims, tested against my own runs | 1:15 | 2:12 | 135 |
| 4 | Three gaps, and what happened to each | 2:12 | 3:01 | 113 |
| 5 | What was built, and what it has to answer | 3:01 | 4:17 | 178 |
| 6 | Software engineering principles, enforced in code | 4:17 | 5:15 | 136 |
| 7 | The tool, end to end | 5:15 | 7:17 | 273 |
| 8 | Screening, per review — never pooled | 7:17 | 8:10 | 123 |
| 9 | What the verifier buys, and why it fails | 8:10 | 9:01 | 119 |
| 10 | Three models, the same 418 records | 9:01 | 9:56 | 128 |
| 11 | Ethical and legal ground | 9:56 | 10:55 | 138 |
| 12 | Automation bias, and why a decision is withheld | 10:55 | 11:48 | 125 |
| 13 | Bias and culture — one measured, one in the data | 11:48 | 13:37 | 254 |
| 14 | A decision you can check | 13:37 | 14:59 | 190 |

---

## Slide 1 — Beyond Retrieval

[0:00 — 0:28]

Good afternoon. I'm Kavindu Gunawardena, and this is Beyond Retrieval. It answers a research question with a ranked, screened set of papers, and it tells you whether other authors have already written that question down as an open gap.

Everything here was measured: twelve and a half thousand records, six reviews, a hundred and one stored runs. Every number on these slides has a directory behind it.

## Slide 2 — Two burdens — and only one is being worked on

[0:28 — 1:15]

The problem has two halves. Screening: a review starts with thousands of candidates and ends with dozens. Here, twelve and a half thousand records yielded three hundred and fifty-one eligible papers, and a human read every abstract.

The second burden is absence — the question nobody has answered. You cannot read your way to it, because the answer is in none of the papers in front of you. Bolaños surveyed twenty-one review tools against thirty-four features. Not one addressed absence.

And the screening half is less settled than it looks. Three recent papers say the published recall figures do not travel between corpora. So I tested all three.

## Slide 3 — Three published claims, tested against my own runs

[1:15 — 2:12]

So this is my literature review, done as a test rather than a summary.

Hida reports that the same model changes its mind between runs. I reproduced it: five repeats with the cache off agreed perfectly, at temperature zero. Not one vendor's quirk.

Khraisha predicted accuracy would be best where prevalence is high. In my six reviews it was not. The quantity that moves is the verification rate — thirty-six to ninety-five per cent — and it does not follow prevalence. An accuracy figure published without a verification rate has a denominator that moves without telling you.

And Kusa's warning is confirmed outright. One unchanged BM25 baseline scores point five two on one review and point zero three eight on another — fourteen-fold, from the corpus alone. That is why nothing here is ever pooled.

## Slide 4 — Three gaps, and what happened to each

[2:12 — 3:01]

Assessment One named three gaps. Here is what happened to each.

One: the field demonstrates capability but ships no open systems anyone can evaluate. Addressed — open licence, public repository, and every figure traced to one of a hundred and one run directories.

Two: cost and reproducibility are uncharacterised. Measured — thirteen cents for the whole comparison, and byte-identical metrics on repeat runs.

Three: absence is unaddressed. Measured, with a caveat. Precision is eighty-eight per cent over seventy-four rated statements; recall is between point four and one. It is precise, and it misses. I report both halves, because reporting only the precision is the kind of claim this project exists to argue against.

## Slide 5 — What was built, and what it has to answer

[3:01 — 4:17]

This is the system as delivered, not as planned. Four layers: one page, an API, the domain logic in services, one adapter per external dependency.

The two boxes at the bottom are the point. The product imports nothing from the evaluation code. My supervisor asked what the six benchmark reviews were for in the product, and the honest answer was nothing: they are the test harness. So I rebuilt the interface as one page, and that separation is now enforced by tests. And everything funnels through the shaded box: the span verifier.

It has to answer two questions. The first is about trust, and I refuse to treat trust as an attitude you survey people about. It is four properties enforced in code, each carrying a number: verifiable, accurate, reproducible, overridable.

The second is practical — how much work this removes, at what cost, and whether it can find the gaps authors state themselves. A missed paper costs a reviewer far more than a false positive, so effort saved is only ever reported at ninety-five per cent recall.

[Only if asked — the counts on this diagram are read off the repository when it is drawn, so they cannot drift from what is actually there. Three of them had, before I made them count.]

## Slide 6 — Software engineering principles, enforced in code

[4:17 — 5:15]

Which principles earned their place.

Separation of concerns. The proof is not the diagram — it is that I replaced six panels with one page, modified no service, and no measured figure moved.

Interface segregation: one provider protocol, four implementations — which is why adding a third vendor was a single class.

Fail fast. The budget ceiling aborts a run rather than warning me afterwards; a stale cache entry raises rather than serving.

Tests as design decisions: five hundred and seventy-four. A subset tests commitments — that ground truth can never reach a prompt — and the mock provider lies twenty per cent of the time on purpose, so the failure path runs on every pass.

And reproducibility: the metrics file is a pure function of configuration and corpus, which makes it testable rather than claimed.

## Slide 7 — The tool, end to end

[5:15 — 7:17]  DEMO VIDEO, 1:45, on the slide. Say the lead-in, start it, stay quiet, then say the closing line.

LEAD-IN: "Rather than describe the tool, here is a minute and three quarters of it."

CLOSING LINE: "Both models saw every question, and each paper says whether they agreed — one of those ten did not. It cost under half a cent."

--- What the recording shows, in order ---

If asked about the speed-up: the screening stretch is the only edit, it is labelled on screen while it runs, and it took sixty-five seconds in real time.

0:00-0:12  The welcome card: search real literature, every answer carries its sentence, you choose what to read.

0:12-0:25  A plain research question is typed. The caption underneath names both models before anything runs, and the slider asks for ten papers.

0:25-1:02  The run: OpenAlex search, SPECTER2 ranking, then screening — and the bar counts papers, not model calls. This stretch is sped up and labelled on screen; it took sixty-five seconds in real time.

1:02-1:20  What came back: fifty candidates ranked, ten suggested, nine addressing the question, three stating a gap, and one where the two models disagreed. The cost line splits the spend by vendor, and the caveat underneath says agreement measures consistency, not correctness.

1:20-1:45  The gap signal: where authors state a gap in their own abstract, their words are quoted back, closest to the question first, each one found verbatim in that paper’s abstract.

NOT IN THE VIDEO: full-text retrieval and export sit behind sign-in, so they are not in this cut. If asked, they are section 11.7 of the report and the right-hand side of the process figure. Offer to show them live.

The recording is driven by scratchpad/demo_drive.py against the running app with both vendors live. It is not a mock-up.

## Slide 8 — Screening, per review — never pooled

[7:17 — 8:10]

Here is the screening result, and why it is not one number.

The bars are the verification rate — the share of decisions whose supporting quote was actually found, word for word, in the record. The reviews are ordered by prevalence, and the rate plainly does not follow it.

This is the column almost nobody reports, and I think it is the most important one, because a decision whose quote cannot be found is not a wrong prediction. It is a referral back to the human.

Recall, where computed, is above point nine on two reviews and point three two on a third — which rises to point eight one once withheld referrals are counted the way a reviewer would actually read them.

## Slide 9 — What the verifier buys, and why it fails

[8:10 — 9:01]

Two results about the verifier, and the first is uncomfortable.

I replayed all twelve and a half thousand decisions with the gate switched off. Recall goes up on every single review — so the verifier costs me recall. What it buys is volume: thirteen records to read instead of four hundred and fifty-one. That is a trade, and I present it as one.

The second result changed how I describe this project. Of five thousand nine hundred verification failures, twelve were genuine fabrications. Ninety-eight per cent were the model echoing my own eligibility criteria back at me.

That is not a deceptive model — it is a measure of my prompt quality, which is far more useful to know.

## Slide 10 — Three models, the same 418 records

[9:01 — 9:56]

This is the result my Assessment Two report had to call designed but unexecuted. It ran this week.

The same four hundred and eighteen records, the same prompt, the same gate, three models. The local model flags seventy-four. Gemini flags a hundred and twenty-five — sixty-nine per cent more. ChatGPT flags ninety, for two cents.

Agreement runs from point five eight to point nine two across the reviews — the same shape as the BM25 finding. Pooled, it would be dominated by whichever review was easiest. So it is not pooled.

The union of all three gives a hundred and forty-five instead of seventy-four. Tempting, since recall is my weakness — but I will not claim it is better until somebody hand-rates it. Agreement measures consistency, not correctness.

## Slide 11 — Ethical and legal ground

[9:56 — 10:55]

Ethics is the part of this project I found hardest to be honest about. Four things.

Data minimisation: sign-in is identity scope only. No password or token is stored, and a test asserts that one account cannot read another's projects.

A residual risk I name rather than hide: the one-time sign-in ticket travels as a URL parameter. Single use and browser-bound — but it still lands in browser history.

Licensing was checked before use, and the details are on the slide.

And the one I would rather not have on a slide. The ethics application for the usability study was planned for week seven and has not been submitted. It is a live risk. It blocks the exit test with a second person, and no measured result — those are scored against a published benchmark, not against people.

## Slide 12 — Automation bias, and why a decision is withheld

[10:55 — 11:48]

This is the measurement I would keep if I could keep only one.

Automation bias is the risk that a researcher stops checking because the tool sounds sure. So I measured how sure it sounds. Across twenty-three thousand decisions, mean confidence when the quote was genuinely found was point eight one three. When no quote could be found at all, point seven nine eight.

Fifteen thousandths apart. No threshold separates them. So a confidence score here would not be a safeguard — it would look like one, which is worse.

The design does the opposite: no confidence number is ever shown, and a decision that cannot be substantiated is withheld and referred. Of thirteen dispositions, nine were human overrides — all thirteen matching ground truth.

## Slide 13 — Bias and culture — one measured, one in the data

[11:48 — 13:37]

Three biases sit inside this system. I can quantify one, and I will not pretend I can quantify the other two.

The first is disciplinary, and it is mine. Four extraction fields come straight from clinical trial reporting conventions. Over the software engineering review, sample size verifies on under eight per cent of records. A tool presenting those fields as universal would under-serve everyone outside medicine invisibly, by returning blanks.

The second is language: English only. A limitation of the evaluation, not a design choice.

The third is source coverage. OpenAlex under-covers Chinese scholarship, and only about half of indexed papers have a redistributable abstract — which is what my pipeline reads. A paper without one is invisible here. That bias I built, and the honest response is to say so.

And culture is not a paragraph I added to satisfy a rubric. It is a variable sitting in my data. These bars are the share of abstracts whose authors state an open gap in their own words: under four per cent in software engineering, fifty-two per cent in one medical review. That is not a difference in how much research remains — it is a difference in what each field considers normal to write.

So if a software engineering researcher runs this and it reports no gaps found, the tool has reported a house style, and they will hear a finding. Three adaptations follow: a schema configurable per discipline, every suggestion shown beside that discipline's base rate, and a tool that stays keyless.

## Slide 14 — A decision you can check

[13:37 — 14:59]

Four things are still open, and I would rather say them than have them found.

The usability exit test needs ethics approval and a participant. Until then the usability claim is withdrawn — not softened, withdrawn. The five thousand nine hundred failure classifications are automatic, and need a manual pass before I call them measured. Full-text extraction stays a demonstration. And the gap recall range supports a direction, not a number.

And the comparison that does not flatter me: ASReview beats every retrieval strategy I built, because it retrains on true labels as the reviewer works and mine rank once. That points straight at adaptive re-ranking, and it belongs in the report precisely because it is uncomfortable.

So the contribution is not that a model can screen papers. It is that a researcher can check it. Every decision carries the sentence it rests on, or it is withheld. Every figure traces to a run directory with its commit hash. And the question nobody has answered yet gets a first, measured attempt — quoted in the words of the authors who asked it.

Thank you. I am happy to take questions.

