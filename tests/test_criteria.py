"""Tests for eligibility criteria loading and provenance.

The criteria are in every prompt. The text screened against must be the
pinned published text, or be visibly marked as a draft.
"""

from __future__ import annotations

import hashlib

import pytest

from slr.db import connect
from slr.services import criteria

TOML = b'''version = 1.0

[[datasets]]
key = "Nelson_2002"

[datasets.publication]
doi = "10.1001/jama.288.7.872"
eligibility_criteria = """
Studies were included if they compared HRT users with non-users."""

[[datasets]]
key = "Wahono_2015"
active = false

[datasets.publication]
url = "http://example.org"
'''


def test_parse_keeps_only_entries_with_criteria():
    parsed = criteria.parse_datasets_toml(TOML)
    assert parsed == {"Nelson_2002": "Studies were included if they compared HRT users with non-users."}


def test_cached_file_matching_the_pin_is_used(tmp_path):
    path = tmp_path / "datasets.toml"
    path.write_bytes(TOML)
    parsed = criteria.fetch_published(
        path, url="http://unused.invalid", expected_sha256=hashlib.sha256(TOML).hexdigest()
    )
    assert "Nelson_2002" in parsed


def test_cached_file_not_matching_the_pin_is_refused(tmp_path):
    path = tmp_path / "datasets.toml"
    path.write_bytes(TOML + b"\n# edited upstream\n")
    with pytest.raises(ValueError, match="not the pinned criteria text"):
        criteria.fetch_published(
            path, url="http://unused.invalid", expected_sha256=hashlib.sha256(TOML).hexdigest()
        )


def test_pin_is_filled_in():
    assert len(criteria.SYNERGY_COMMIT) == 40
    assert len(criteria.SYNERGY_TOML_SHA256) == 64


def test_review_without_stored_criteria_is_a_draft(tmp_path):
    conn = connect(tmp_path / "c.db")
    c = criteria.for_review(conn, "Nelson_2002")
    assert c.status == criteria.DRAFT
    assert c.text == criteria.DRAFT_CRITERIA["Nelson_2002"]


def test_stored_criteria_are_published(tmp_path):
    conn = connect(tmp_path / "c.db")
    criteria.store(conn, "Nelson_2002", "first", "src")
    criteria.store(conn, "Nelson_2002", "published text", "src@abc")
    c = criteria.for_review(conn, "Nelson_2002")
    assert (c.text, c.status, c.source) == ("published text", criteria.PUBLISHED, "src@abc")
    stored = conn.execute("SELECT sha256 FROM review_criteria").fetchone()[0]
    assert stored == c.sha256


def test_every_evaluation_review_has_a_draft():
    from slr.config import SUBSET

    assert set(criteria.DRAFT_CRITERIA) == set(SUBSET)
