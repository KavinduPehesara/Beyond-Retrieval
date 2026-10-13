# End-to-end check — 14 October 2026

A functional check, not a benchmark. No reported figure moved; no model was
called for a number; $0 spent. The point was to replace "the app works" with a
checked claim before the report describes it.

## Method

The real six-review database (12,598 records, counts verified per review),
`uvicorn` serving `slr.api.app`, 53 API calls across every route family, then
all seven page scripts driven by Streamlit's own `AppTest` **against the live
API rather than monkeypatched stubs**. That last part is what the existing page
tests cannot do: they stub `api_client`, so they prove a page handles the
response *shape* and say nothing about what the API actually returns.

## What held up

- Full suite **502 passing** (496 before this check's three fixes). The 7
  `test_dense_retrieve` failures recorded previously were a missing `faiss` in
  the checking environment only; with faiss present all 10 pass.
- All seven pages render against the live API with **zero exceptions and zero
  error blocks**.
- 49 of 53 API calls returned 200. Every per-review route — metrics, criteria,
  extraction summary, papers, gaps — works on all six reviews. Paper detail,
  override summary and all eight `/charts/*` routes return well-formed payloads.
- `GET /discover/sessions` correctly returns **401** without a token. Not a
  defect; the account boundary doing its job.
- `random` and `bm25` ranking return ranked candidates immediately.

## Three defects found, all fixed

**1. A failing rank reached the page as a raw traceback.**
`app/pages/3_Validation_Screening.py` called `query_rank` unguarded, so any
failure surfaced as `httpx.HTTPStatusError: Server error '500 Internal Server
Error'` — true, and useless to a researcher. Every other client call in the app
is already wrapped, including the live-screen call twenty lines below it and the
full-text fetch on Run a Review, which even distinguishes a bad response from a
timeout. This one was the exception. Now guarded the same way, and it shows the
API's own `detail` sentence rather than the status line.

**2. The dashboard offered a retrieval strategy it cannot promptly serve.**
Only **four of six** reviews have cached SPECTER2 vectors — week 9's exit test
only needed three reviews, and the schedule moved on:

| Review | Records | Vectors cached |
|---|---|---|
| Menon_2022 | 975 | yes |
| Nelson_2002 | 366 | yes |
| Radjenovic_2013 | 5,935 | **no** |
| Smid_2020 | 2,627 | yes |
| van_der_Valk_2021 | 725 | yes |
| van_der_Waal_2022 | 1,970 | **no** |

The strategy picker offered `dense`/`hybrid`/`rerank` for all six with no
indication. A first dense query on Radjenović_2013 would embed 5,935 abstracts
with SPECTER2 on CPU inside the request that asked for it — minutes behind a
spinner with no progress, and a plausible timeout. The same page already
explains this distinction for the semantic map ("only available for reviews a
dense/hybrid config has been run on"); the picker didn't. `GET /reviews` now
reports `embeddings_cached` per review and the page warns before the click,
naming the record count and pointing at `bm25`.

**3. `/query` returned a bare 500 for anything that wasn't a `ValueError`.**
Only `ValueError` was mapped to a 400, so a missing optional package, an OOM, or
any other failure became `Internal Server Error` with no body — which is why the
client had nothing to show in defect 1. `ImportError` now returns 503 naming the
missing package, any other failure returns 503 naming the exception type and
message, and the pre-existing 400 for an unknown strategy still takes
precedence.

Six tests added (four API, two page), each asserting the specific failure that
was observed rather than the fix in the abstract.

## Limits of this check

Dense, hybrid and rerank ranking could not be exercised end to end here: the
checking environment lacks the `adapters` library SPECTER2 needs, so those three
returned the new 503 rather than real rankings. That path is proven by week 9's
run directories on the author's machine, not by this check. The cold-embedding
timing in defect 2 is inferred from CLAUDE.md's recorded "~20 min for all three
reviews from cold" and was not measured.

No Gemini or OpenAI call was made. Ollama was not running, so live screening and
the Discover path were not exercised; both are covered by the 8 October check.
Google sign-in was not exercised against the real provider — no credentials are
configured. Concurrent-writer behaviour was not tested beyond the single
regression added on 8 October.
