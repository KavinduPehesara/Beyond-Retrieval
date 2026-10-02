"""Tests for turning a finished ASReview simulation into a comparable
TNR@95/WSS@95 figure. The trickiest part isn't the metric (that's
``ranking_metrics``, already tested elsewhere) -- it's correctly rebuilding
a full-review ranking from a simulation that stopped early.
"""

from __future__ import annotations

import csv
import sqlite3
import zipfile

import pytest

from slr.eval.asreview_report import build_ranking


def _write_fake_project(path, queried_record_ids):
    """A minimal .asreview zip: just enough structure for build_ranking to
    read the query order out of results.sql, the same shape a real
    ``asreview simulate`` run produces."""
    db_path = path.with_suffix(".sqlite")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE results (record_id INTEGER, label INTEGER)")
    for rid in queried_record_ids:
        conn.execute("INSERT INTO results (record_id, label) VALUES (?, 0)", (rid,))
    conn.commit()
    conn.close()

    with zipfile.ZipFile(path, "w") as zf:
        zf.write(db_path, "reviews/fake/results.sql")


@pytest.fixture()
def export_csv(tmp_path):
    out = tmp_path / "export.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["work_id", "title", "abstract", "label_included"])
        for i in range(5):
            writer.writerow([f"W{i}", f"title {i}", f"abstract {i}", 1 if i in (0, 2) else 0])
    return out


def test_ranking_starts_with_the_queried_order(export_csv, tmp_path):
    project = tmp_path / "project.asreview"
    _write_fake_project(project, queried_record_ids=[2, 0])  # stopped after both includes found

    ranked_ids, labels = build_ranking(export_csv, project)

    assert ranked_ids[:2] == ["W2", "W0"]
    assert labels == {"W0": 1, "W1": 0, "W2": 1, "W3": 0, "W4": 0}


def test_never_queried_records_are_appended_once_each(export_csv, tmp_path):
    project = tmp_path / "project.asreview"
    _write_fake_project(project, queried_record_ids=[2, 0])

    ranked_ids, _ = build_ranking(export_csv, project)

    assert sorted(ranked_ids) == ["W0", "W1", "W2", "W3", "W4"]
    assert len(ranked_ids) == 5
    # appended in original dataset order, after the two that were actually queried
    assert ranked_ids[2:] == ["W1", "W3", "W4"]
