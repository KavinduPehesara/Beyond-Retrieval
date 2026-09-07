# Local setup — do this once

About twenty minutes.

---

## 1. Clone

```bash
git clone https://github.com/KavinduPehesara/Beyond-Retrieval.git
cd Beyond-Retrieval
```

If git has never been used on this machine:

```bash
git config --global user.name "Pehesara Gunawardena"
git config --global user.email "your-github-email@example.com"
git config --global init.defaultBranch main
```

Use the same email as the GitHub account, or commits will not link to the
profile — which matters when the repository is the evidence of the work.

---

## 2. Environment

Python 3.11.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

Versions are pinned. Do not upgrade a package mid-project without a reason you
would be willing to write in the limitations section.

---

## 3. Secrets — do this before getting an API key

This repository is **public**. A key committed here is scraped by bots within
seconds, and rewriting history does not un-leak it. Ten seconds of checking now
prevents the one mistake in this project that cannot be undone.

```bash
copy .env.example .env          # Windows
git status
```

`.env` must **not** appear in the output. If it does, stop and fix `.gitignore`
before continuing.

Second check:

```bash
git check-ignore -v .env
```

That should print the `.gitignore` line that matches it.

Only once both checks pass, get a key from
<https://aistudio.google.com/apikey> and paste it into `.env`.

### If a key ever does get committed

1. Revoke it in Google AI Studio **immediately**.
2. Generate a new one.
3. Only then worry about cleaning history.

Revoking first is what matters. A dead key in history is embarrassing; a live
one is a bill.

---

## 4. Turn on push protection

GitHub → Settings → Code security → **Secret scanning** and **Push protection**.
Free on public repositories. It blocks a push containing anything shaped like an
API key — exactly the mistake worth blocking.

---

## 5. Get the data

```bash
python -m synergy_dataset get
```

Then load only the six reviews in the evaluation subset: Radjenović_2013,
Smid_2020, van_der_Waal_2022, Menon_2022, van_der_Valk_2021, Nelson_2002 —
12,598 records in total. Do not load all twenty-six; they will get screened by
accident and the budget will go with them.

---

## 6. Working rhythm

Commit small and often. Run artefacts carry a git SHA, which only works if you
commit before running.

```bash
git add -A
git commit -m "feat: add span verifier and unit tests"
git push
```

Write messages that say what changed and why, not "update". In week 15 you will
be reconstructing what happened in week 9, and the commit log is the only
record that is not memory.

| Prefix | For |
|---|---|
| `feat:` | New capability |
| `fix:` | Corrected behaviour |
| `eval:` | Experiment run, metrics, analysis |
| `docs:` | README, proposal, supervisor reports |
| `chore:` | Dependencies, config, housekeeping |

One branch (`main`) is fine for a solo fifteen-week project. Branching costs
time and buys nothing when there is no one to merge with.

---

## 7. Tag each week

At the end of each week, tag it. This makes "the state of the system at the
week 10 exit test" something to check out rather than something to remember.

```bash
git tag -a week-07 -m "Walking skeleton: 50 records screened, all spans verified"
git push origin week-07
```

---

## Week 7 exit test

Fifty records screened end to end, every accepted decision carrying a span
found verbatim in its own abstract, spend under one dollar, and `pytest` green
on the span verifier.
