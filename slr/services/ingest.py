"""Load SYNERGY reviews into SQLite.

Records come from the SYNERGY v1.0 release through the ``synergy-dataset``
package; published eligibility criteria come from the pinned
``datasets.toml`` (see ``slr.services.criteria``). Neither is committed.

Each record arrives as an OpenAlex Work with a ``label_included`` value
recording what the human reviewers actually decided. That column is written
here and read only by ``slr.eval.metrics``. It does not appear in any prompt.
Keeping that boundary is what makes the accuracy figures mean anything.

Every review is loaded in full. Capping happens at screening time, never here:
a capped ingest changes the prevalence of what is stored, and every metric
computed afterwards would inherit the distortion without saying so.

SYNERGY's licence note: abstracts may not be republished as plain text. They
live only in ``data/slr.db`` and in ``responses.jsonl``, both gitignored.
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from pathlib import Path

from slr.config import Config, load_config
from slr.db import connect
from slr.services import criteria as criteria_service

UPSERT = """
INSERT INTO work
    (review, work_id, doi, title, abstract, year, venue, publisher, country,
     language, label_included)
VALUES (?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(review, work_id) DO UPDATE SET
    doi = excluded.doi,
    title = excluded.title,
    abstract = excluded.abstract,
    year = excluded.year,
    venue = excluded.venue,
    publisher = excluded.publisher,
    country = excluded.country,
    language = excluded.language,
    label_included = excluded.label_included
"""

SYNERGY_FIELDS = ["doi", "title", "abstract", "publication_year"]


def _load_synergy(review: str):
    """Return a DataFrame for one SYNERGY review, one row per labelled record.

    Built from ``Dataset.labels`` and ``Dataset.to_dict`` rather than
    ``Dataset.to_frame``. ``to_frame`` puts ``openalex_id`` in the index, not
    a column, and a labelled record whose work is absent from the release
    comes back as an all-empty row with no label. Here every record in
    ``labels.csv`` is kept with its label; a missing work simply has no
    title or abstract.

    The release is downloaded on first use to ``~/.synergy_dataset_source``,
    outside the repository. A local CSV at ``data/synergy/<review>.csv`` is
    used instead when the package is not installed.
    """
    import pandas as pd

    try:
        from synergy_dataset.base import Dataset, _dataset_available, download_raw_dataset
    except ImportError as exc:
        fallback = Path("data/synergy") / f"{review}.csv"
        if fallback.exists():
            return pd.read_csv(fallback)
        raise RuntimeError(
            f"synergy-dataset is not installed and no CSV exists at {fallback}. "
            f"pip install -r requirements.txt"
        ) from exc

    if not _dataset_available():
        download_raw_dataset()

    dataset = Dataset(review)
    try:
        labels = dataset.labels
    except FileNotFoundError as exc:
        raise RuntimeError(f"SYNERGY has no review named {review!r}") from exc
    records = dataset.to_dict(SYNERGY_FIELDS)

    rows = []
    for work_id in sorted(labels):
        record = records.get(work_id) or {}
        rows.append(
            {
                "openalex_id": work_id,
                "doi": record.get("doi"),
                "title": record.get("title"),
                "abstract": record.get("abstract"),
                "publication_year": record.get("publication_year"),
                "label_included": labels[work_id],
            }
        )
    return pd.DataFrame(rows)


def _column(frame, *names: str):
    for n in names:
        if n in frame.columns:
            return frame[n]
    return None


def _is_missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        import pandas as pd
    except ImportError:  # pragma: no cover
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def clean_text(value) -> str | None:
    """Missing stays missing.

    ``str(nan)`` is ``"nan"``. A model shown ``ABSTRACT: nan`` is screening a
    record with no abstract without being told so, and the verifier cannot
    report ``no_source_text`` for a source that is the string "nan".
    """
    if _is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def clean_year(value) -> int | None:
    """Accepts 2019, "2019" and 2019.0 — a year column with gaps is float."""
    text = clean_text(value)
    if text is None:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else None


def clean_label(value, review: str, work_id: str) -> int:
    """Ground truth must be exactly 0 or 1. Anything else stops the ingest."""
    if _is_missing(value):
        raise ValueError(f"{review}/{work_id}: label_included is missing")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{review}/{work_id}: label_included is {value!r}") from None
    if number not in (0.0, 1.0):
        raise ValueError(f"{review}/{work_id}: label_included is {value!r}")
    return int(number)


def ingest_frame(conn: sqlite3.Connection, review: str, frame) -> int:
    """Load one review's records. Returns the number of distinct records.

    Safe to run repeatedly: records are upserted, so the FTS index stays
    consistent and a second ingest leaves the database unchanged.
    """
    labels = _column(frame, "label_included", "included", "label")
    if labels is None:
        raise ValueError(f"{review}: no label column, so it cannot be evaluated")

    titles = _column(frame, "title")
    abstracts = _column(frame, "abstract")
    ids = _column(frame, "openalex_id", "id", "work_id")
    dois = _column(frame, "doi")
    years = _column(frame, "publication_year", "year")

    rows: dict[str, tuple] = {}
    for i in range(len(frame)):
        work_id = clean_text(ids.iloc[i]) if ids is not None else None
        work_id = work_id or f"{review}:{i}"
        label = clean_label(labels.iloc[i], review, work_id)

        if work_id in rows:
            if rows[work_id][-1] != label:
                raise ValueError(
                    f"{review}/{work_id}: appears twice with different labels"
                )
            continue

        rows[work_id] = (
            review,
            work_id,
            clean_text(dois.iloc[i]) if dois is not None else None,
            clean_text(titles.iloc[i]) if titles is not None else None,
            clean_text(abstracts.iloc[i]) if abstracts is not None else None,
            clean_year(years.iloc[i]) if years is not None else None,
            None,  # venue      — populated in week 9
            None,  # publisher  — populated in week 9
            None,  # country    — populated in week 9
            None,  # language   — NULL until detection exists; never guessed
            label,
        )

    conn.executemany(UPSERT, list(rows.values()))
    conn.commit()
    return len(rows)


def ingest_review(conn: sqlite3.Connection, review: str) -> int:
    """Load one review in full."""
    return ingest_frame(conn, review, _load_synergy(review))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load SYNERGY reviews into SQLite.")
    parser.add_argument("--config", required=True, help="Path to a config YAML")
    args = parser.parse_args(argv)

    cfg: Config = load_config(args.config)
    conn = connect(cfg.db_path)
    published = criteria_service.fetch_published()

    total = 0
    for review in cfg.dataset.reviews:
        n = ingest_review(conn, review)
        total += n
        included, no_abstract = conn.execute(
            "SELECT SUM(label_included), SUM(abstract IS NULL) FROM work WHERE review = ?",
            (review,),
        ).fetchone()
        rate = 100 * included / n if n else 0
        print(
            f"  {review:20} {n:>6} records, {included:>4} included ({rate:.1f}%), "
            f"{no_abstract:>4} without abstract"
        )

        if review in published:
            criteria_service.store(conn, review, published[review], criteria_service.SOURCE)
        else:
            print(f"  ! no published criteria for {review}; drafts will be used")

    print(f"\n{total} records in {cfg.db_path}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
