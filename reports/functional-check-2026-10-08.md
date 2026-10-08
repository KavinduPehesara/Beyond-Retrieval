# Functional check — 8 October 2026

This is a functional smoke test, not a benchmark or a new accuracy result.

- Automated suite after the fix: 437 passed, two dependency deprecation warnings.
- All seven Streamlit page scripts rendered through AppTest against the live API without exceptions.
- Live metrics, criteria, extraction summaries, paper lists and gaps returned HTTP 200 for all six reviews.
- Corpus, trust, gaps, performance, and Nelson confidence, recall-curve, extraction and semantic-map chart endpoints returned HTTP 200.
- Random, BM25, dense, hybrid and rerank retrieval each returned three papers.
- Paper details, override summary and cached screening were exercised successfully. Override writes were covered by isolated automated tests; no artificial human override was added to the real corpus.
- A browser search for vitamin D supplementation randomized trials completed with five papers: four verified keeps, one referral, study-detail extraction and one gap statement.
- Live full-text lookup and local extraction completed for DOI 10.1136/bmj.m2329. Europe PMC supplied a 1,058-character fragment, correctly flagged by the API, with one verified field and four not-stated fields. This does not establish complete-paper extraction quality.

## Bug found and fixed

Opening a second page during discovery produced HTTP 500 database-lock errors. `connect()` rewrote schema metadata on every connection, taking a writer lock even for read-only routes. Existing current-version databases now open without schema writes, while preserving per-connection foreign-key enforcement. New regression coverage opens and reads a second connection while the first holds a write transaction.

## Remaining limitations

The live model incorrectly kept a meta-analysis under trial-only criteria and classified its design as a randomized controlled trial. Another extracted sample size was `s803` although the quote contained 803. Quote existence verification does not establish decision correctness or that the extracted value accurately represents the quote. These are observed model-quality issues, not passing accuracy checks.

Gemini calls were not exercised. No paid calls were made. Not every widget combination or external failure mode was manually exercised. Two local write-heavy requests overlapped during the initial lock reproduction; this check does not establish concurrent-writer throughput.
