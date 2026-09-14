"""Eligibility criteria: the published text, with provenance.

SYNERGY records each review's eligibility criteria, quoted from the original
publication, in ``datasets.toml`` in the synergy-dataset repository. They are
not part of the v1.0 data release, so they are fetched separately — from a
pinned commit, checked against a known hash. The criteria are part of every
prompt; a silent upstream edit would change every screening decision.

The text is not committed to this repository, because it is quoted from
third-party publications. It is cached under ``data/`` (gitignored), stored in
the database by ingest, and every metrics file records its hash.

A review with no stored criteria falls back to the one-line working drafts in
``DRAFT_CRITERIA``. Those are marked ``working-draft`` wherever they are used,
so a figure produced under them cannot be mistaken for a reportable one.
"""

from __future__ import annotations

import hashlib
import sqlite3
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# "Add eligibility criteria to datasets.toml" (asreview/synergy-dataset#115),
# the latest commit touching the file as of September 2026.
SYNERGY_COMMIT = "ca8cb9e2ea97195bee7ba6197153d633f5cee85f"
SYNERGY_TOML_SHA256 = "8c714ce8619ebd385c0311a99b6320f67e8c7b7346c726e84a4f76007247a1a4"
SYNERGY_TOML_URL = (
    f"https://raw.githubusercontent.com/asreview/synergy-dataset/{SYNERGY_COMMIT}/datasets.toml"
)
SOURCE = f"asreview/synergy-dataset@{SYNERGY_COMMIT[:12]}:datasets.toml"
CACHE_PATH = Path("data/synergy/datasets.toml")

PUBLISHED = "published"
DRAFT = "working-draft"

# One-line topic summaries, used only when no published criteria are stored:
# by the tests, and by anyone running the pipeline before ingest.
DRAFT_CRITERIA: dict[str, str] = {
    "Radjenovic_2013": (
        "Include empirical studies that validate or compare software metrics "
        "for software fault prediction."
    ),
    "Smid_2020": (
        "Include simulation studies comparing Bayesian and frequentist "
        "estimation of structural equation models in small samples."
    ),
    "van_der_Waal_2022": (
        "Include original studies of adults with cancer in western healthcare "
        "systems reporting their preferred role in treatment decisions."
    ),
    "Menon_2022": (
        "Include systematic reviews of non-acute environmental exposures and "
        "health outcomes."
    ),
    "van_der_Valk_2021": (
        "Include studies reporting cross-sectional associations between hair "
        "glucocorticoids and measures of obesity."
    ),
    "Nelson_2002": (
        "Include studies comparing hormone replacement therapy users with "
        "non-users that report clinical outcomes."
    ),
}


@dataclass(frozen=True)
class Criteria:
    """The criteria a review is screened against, and how far to trust them."""

    text: str
    status: str  # published | working-draft
    source: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def parse_datasets_toml(content: bytes) -> dict[str, str]:
    """review key -> eligibility criteria text, for entries that have one."""
    data = tomllib.loads(content.decode("utf-8"))
    published: dict[str, str] = {}
    for entry in data.get("datasets", []):
        text = entry.get("publication", {}).get("eligibility_criteria")
        if text and text.strip():
            published[entry["key"]] = text.strip()
    return published


def fetch_published(
    cache_path: Path = CACHE_PATH,
    *,
    url: str = SYNERGY_TOML_URL,
    expected_sha256: str = SYNERGY_TOML_SHA256,
) -> dict[str, str]:
    """Published criteria for every SYNERGY review, from the pinned commit.

    Downloaded once and cached. The bytes must match the pinned hash whether
    they come from the cache or the network; anything else is refused.
    """
    cached = cache_path.exists()
    if cached:
        content = cache_path.read_bytes()
    else:
        with urllib.request.urlopen(url, timeout=60) as response:
            content = response.read()

    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        where = cache_path if cached else url
        raise ValueError(
            f"{where} has sha256 {digest}, expected {expected_sha256}. This is "
            f"not the pinned criteria text. Delete the cached file, or update "
            f"the pin in slr/services/criteria.py deliberately."
        )

    if not cached:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(content)
    return parse_datasets_toml(content)


def store(conn: sqlite3.Connection, review: str, text: str, source: str) -> None:
    """Record the published criteria for a review. Called by ingest."""
    conn.execute(
        "INSERT INTO review_criteria (review, criteria, source, sha256) VALUES (?,?,?,?) "
        "ON CONFLICT(review) DO UPDATE SET criteria = excluded.criteria, "
        "source = excluded.source, sha256 = excluded.sha256",
        (review, text, source, hashlib.sha256(text.encode("utf-8")).hexdigest()),
    )
    conn.commit()


def for_review(conn: sqlite3.Connection, review: str) -> Criteria:
    """The criteria to screen a review against: published if stored, else draft."""
    row = conn.execute(
        "SELECT criteria, source FROM review_criteria WHERE review = ?", (review,)
    ).fetchone()
    if row:
        return Criteria(row["criteria"], PUBLISHED, row["source"])
    return Criteria(
        DRAFT_CRITERIA.get(review, "See the review's published protocol."),
        DRAFT,
        "slr/services/criteria.py:DRAFT_CRITERIA",
    )
