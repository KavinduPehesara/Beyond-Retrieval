"""Load SYNERGY reviews into SQLite.

SYNERGY is fetched with ``python -m synergy_dataset get`` and read from there;
it is never committed. Each record arrives as an OpenAlex Work object with a
``label_included`` column recording what the human reviewers actually decided.

That column is written here and read only by ``slr.eval.metrics``. It does not
appear in any prompt. Keeping that boundary is what makes the accuracy figures
mean anything.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from slr.config import Config, load_config
from slr.db import connect

# Eligibility criteria per review. SYNERGY ships these as block quotations
# with each dataset; these are condensed working versions for week 7, to be
# replaced with the published text before any reported run.
CRITERIA: dict[str, str] = {
    "Radjenovic_2013": (
        "Include studies that propose, evaluate or compare software fault "
        "prediction metrics. Exclude studies not concerning fault prediction, "
        "and studies with no empirical evaluation."
    ),
    "Smid_2020": (
        "Include studies that report statistical methodology for structural "
        "equation modelling or Bayesian estimation in small samples. Exclude "
        "purely applied studies with no methodological contribution."
    ),
    "van_der_Waal_2022": (
        "Include studies reporting clinical outcomes for the intervention "
        "under review. Exclude animal studies, case reports and reviews."
    ),
    "Menon_2022": (
        "Include studies reporting original empirical data on the population "
        "and outcome of interest. Exclude protocols, editorials and reviews."
    ),
    "van_der_Valk_2021": (
        "Include studies measuring the exposure and outcome of interest in "
        "human participants. Exclude animal studies and non-empirical work."
    ),
    "Nelson_2002": (
        "Include studies reporting screening or diagnostic accuracy in the "
        "target population. Exclude studies without a reference standard."
    ),
}


def _load_synergy(review: str):
    """Return a DataFrame for one SYNERGY review.

    Tries the ``synergy-dataset`` package first, then a local CSV fallback so
    the pipeline can be exercised without the download.
    """
    try:
        from synergy_dataset import Dataset

        return Dataset(review).to_frame()
    except Exception as exc:
        fallback = Path("data/synergy") / f"{review}.csv"
        if fallback.exists():
            import pandas as pd

            return pd.read_csv(fallback)
        raise RuntimeError(
            f"Could not load SYNERGY review {review!r}: {exc}\n"
            f"Run `python -m synergy_dataset get` first, or place a CSV at "
            f"{fallback}."
        ) from exc


def _column(frame, *names: str):
    for n in names:
        if n in frame.columns:
            return frame[n]
    return None


def ingest_review(conn: sqlite3.Connection, review: str, limit: int | None) -> int:
    """Load one review. Returns the number of records inserted."""
    frame = _load_synergy(review)

    if limit:
        # Stratified head: keep every included record we can, then fill with
        # excluded ones. A random head of a 1%-prevalence review can easily
        # contain zero positives, which makes recall undefined and the smoke
        # test meaningless.
        labels = _column(frame, "label_included", "included", "label")
        if labels is not None:
            positives = frame[labels == 1]
            negatives = frame[labels != 1]
            n_pos = min(len(positives), max(2, limit // 5))
            frame = (
                positives.head(n_pos)
                ._append(negatives.head(limit - n_pos))
                if hasattr(positives, "_append")
                else positives.head(n_pos).append(negatives.head(limit - n_pos))
            )
        else:
            frame = frame.head(limit)

    titles = _column(frame, "title")
    abstracts = _column(frame, "abstract")
    labels = _column(frame, "label_included", "included", "label")
    ids = _column(frame, "openalex_id", "id", "work_id")
    dois = _column(frame, "doi")
    years = _column(frame, "publication_year", "year")

    rows = []
    for i in range(len(frame)):
        work_id = str(ids.iloc[i]) if ids is not None else f"{review}:{i}"
        rows.append(
            (
                work_id,
                review,
                str(dois.iloc[i]) if dois is not None else None,
                str(titles.iloc[i]) if titles is not None else None,
                str(abstracts.iloc[i]) if abstracts is not None else None,
                int(years.iloc[i]) if years is not None and str(years.iloc[i]).isdigit() else None,
                None,  # venue      — populated in week 9
                None,  # publisher  — populated in week 9
                None,  # country    — populated in week 9
                "en",  # language   — detection added in week 9
                int(labels.iloc[i]) if labels is not None else None,
            )
        )

    conn.executemany(
        "INSERT OR REPLACE INTO work "
        "(work_id, review, doi, title, abstract, year, venue, publisher, country, language, label_included) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load SYNERGY reviews into SQLite.")
    parser.add_argument("--config", required=True, help="Path to a config YAML")
    args = parser.parse_args(argv)

    cfg: Config = load_config(args.config)
    conn = connect(cfg.db_path)

    total = 0
    for review in cfg.dataset.reviews:
        n = ingest_review(conn, review, cfg.dataset.max_records)
        total += n
        included = conn.execute(
            "SELECT COUNT(*) FROM work WHERE review = ? AND label_included = 1",
            (review,),
        ).fetchone()[0]
        rate = 100 * included / n if n else 0
        print(f"  {review:24} {n:>6} records, {included:>4} included ({rate:.1f}%)")

    print(f"\n{total} records in {cfg.db_path}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
