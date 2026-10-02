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

Python 3.13 (the venv this project actually runs on; the pins in
`requirements.txt` target it — see that file's header for why this isn't 3.11).

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

One command loads only the six reviews in the evaluation subset —
Radjenović_2013, Smid_2020, van_der_Waal_2022, Menon_2022, van_der_Valk_2021,
Nelson_2002, 12,598 records in total. It downloads the SYNERGY v1.0 release
(~450MB) and the pinned published eligibility criteria on first run:

```bash
python -m slr.services.ingest --config configs/ingest_all.yaml
```

Do not load all twenty-six of SYNERGY's reviews; the other twenty will get
screened by accident and the budget will go with them. `ingest_all.yaml`
lists exactly the six in scope and nothing else.

Verify it matches the recorded figures (`CLAUDE.md`, "Verified on real
data"): 12,598 records across the six reviews, each review's own
record/inclusion counts printed by the command above.

---

## 6. Run the system

```bash
pytest -q                                           # should be all green
python -m slr.eval.harness --config configs/smoke.yaml --require-clean   # mock provider, $0
```

Screen for real at $0 with a local model (install
[Ollama](https://ollama.com) first):

```bash
winget install Ollama.Ollama
ollama pull qwen2.5:7b-instruct     # ~4.7GB, needs ~8GB VRAM
python -m slr.eval.harness --config configs/week08_ollama.yaml --require-clean
```

Then bring up the dashboard:

```bash
uvicorn slr.api.app:app              # backend, localhost:8000
streamlit run app/Home.py            # dashboard, localhost:8501 (needs the API running)
```

Gemini is a second provider (`provider: gemini` in a config) but spends real
money against the $50 ceiling and needs a key — see section 3 above before
adding one to a clone of a public repository.

---

## 7. Working rhythm

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

## 8. Tag each week

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
