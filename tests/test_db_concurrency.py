"""Readers must remain available during a live request's cache writes."""

from slr.db import connect


def test_open_existing_database_while_another_connection_is_writing(tmp_path):
    path = tmp_path / "review.db"
    writer = connect(path)
    try:
        writer.execute("BEGIN IMMEDIATE")
        reader = connect(path)
        try:
            assert reader.execute("SELECT COUNT(*) FROM work").fetchone()[0] == 0
            assert reader.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        finally:
            reader.close()
    finally:
        writer.rollback()
        writer.close()
