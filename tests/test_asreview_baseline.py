"""Tests for the ASReview export — the one other place, besides
eval/metrics.py, allowed to read label_included (see slr/eval/
asreview_baseline.py's docstring for why that's fine here)."""

from __future__ import annotations

import csv

import pytest

from slr.db import connect
from slr.eval.asreview_baseline import export_review


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    c.execute(
        "INSERT INTO work (work_id, review, title, abstract, label_included) VALUES (?,?,?,?,?)",
        ("W1", "Nelson_2002", "A trial of HRT", "Some abstract text.", 1),
    )
    c.execute(
        "INSERT INTO work (work_id, review, title, abstract, label_included) VALUES (?,?,?,?,?)",
        ("W2", "Nelson_2002", "An unrelated study", "Different abstract.", 0),
    )
    c.commit()
    yield c
    c.close()


def test_export_writes_columns_asreview_recognises(conn, tmp_path):
    out = tmp_path / "export.csv"
    n = export_review(conn, "Nelson_2002", out)
    assert n == 2

    with out.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert {r["work_id"] for r in rows} == {"W1", "W2"}
    assert rows[0]["title"] in ("A trial of HRT", "An unrelated study")
    assert {int(r["label_included"]) for r in rows} == {0, 1}


def test_export_rejects_an_unknown_review(conn, tmp_path):
    with pytest.raises(SystemExit):
        export_review(conn, "NoSuchReview", tmp_path / "out.csv")
