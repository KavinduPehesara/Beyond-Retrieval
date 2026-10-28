"""Tests for the project export ZIP. No network: OpenAlex, Europe PMC and the
publishers are an httpx.MockTransport."""

from __future__ import annotations

import csv
import io
import json
import zipfile

import httpx
import pytest

from slr.services.export import build_export, pdf_candidates, safe_name

ASSET_ID = "a" * 64


def _session():
    suggestion = lambda wid, title, status, verified, gap=None: {
        "work_id": f"https://openalex.org/{wid}", "title": title, "year": 2022, "doi": f"https://doi.org/10.1/{wid}",
        "source_url": f"https://example.org/{wid}", "abstract": "An abstract.", "relevance": 0.91,
        "decision": {"status": status, "quote": "we studied children", "span_verified": verified},
        "gap": gap or {"status": "not_stated"},
    }
    return {
        "query": "Does vitamin D reduce asthma attacks?",
        "papers": [
            suggestion("W1", "Vitamin D: a trial / in children?", "include", True,
                       {"status": "gap_stated", "quote": "long-term effects remain unknown"}),
            suggestion("W2", "Paywalled paper", "exclude", True),
        ],
        "fulltext": {"papers": [
            {"work_id": "https://openalex.org/W2", "title": "Paywalled paper", "found": False,
             "note": "in Europe PMC but not open access -- full text is paywalled"},
            {"work_id": "https://openalex.org/W1", "title": "Vitamin D: a trial / in children?", "found": True,
             "pmcid": "PMC1", "note": "full text from PMC1",
             "primary_outcome": {"status": "verified", "value": "fewer attacks", "quote": "fewer attacks were seen"},
             "effect_size": {"status": "unverified", "value": "made up"},
             "tables": [{"label": "Table 1", "caption": "Baseline", "rows": [["Group", "N"], ["A", "40"]]}],
             "figures": [{"label": "Figure 1", "caption": "Flow", "mentions": ["see Figure 1"],
                          "images": [{"name": "fig1.png", "download_url": f"/fulltext/assets/PMC1/{ASSET_ID}"}]}],
             "coverage": [{"key": "methods", "label": "Methods", "status": "extracted", "count": 1, "note": ""}],
             "evidence": {"methods": [{"source": "Methods", "quote": "We recruited 80 children."}]},
             "gaps": [{"value": "Long-term effect is unknown", "section": "Discussion",
                       "quote": "Further research is needed to establish whether the effect persists."}],
             "gaps_note": "found"},
        ]},
    }


def _client(pdf_ok=True):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.openalex.org/works/W1" in url:
            return httpx.Response(200, json={"best_oa_location": {"pdf_url": "https://publisher.example/w1.pdf"},
                                             "locations": []})
        if "api.openalex.org/works/W2" in url:
            return httpx.Response(200, json={"best_oa_location": None, "locations": []})
        if "europepmc/webservices/rest/search" in url:
            return httpx.Response(200, json={"resultList": {"result": [{"fullTextUrlList": {"fullTextUrl": [
                {"documentStyle": "pdf", "availability": "Open access", "url": "https://europepmc.org/articles/PMC1?pdf=render"}]}}]}})
        if url == "https://publisher.example/w1.pdf":
            if pdf_ok:
                return httpx.Response(200, content=b"%PDF-1.7 fake pdf")
            return httpx.Response(200, html="<html>Are you a robot?</html>")
        if "europepmc.org/articles" in url:
            return httpx.Response(403, html="blocked")
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture()
def assets(tmp_path):
    (tmp_path / "PMC1").mkdir()
    (tmp_path / "PMC1" / ASSET_ID).write_bytes(b"\x89PNG fake")
    return tmp_path


def _unzip(data):
    zf = zipfile.ZipFile(io.BytesIO(data))
    return {name: zf.read(name) for name in zf.namelist()}


def test_safe_name_is_valid_on_windows():
    assert safe_name('Vitamin D: a trial / in children?') == "Vitamin D a trial in children"
    assert safe_name("") == "untitled"
    assert safe_name("x" * 200, 10) == "x" * 10


def test_the_export_is_one_folder_per_paper_in_suggestion_order(assets):
    name, data = build_export(_session(), client=_client(), assets_dir=assets)
    files = _unzip(data)
    root = "Beyond Retrieval - Does vitamin D reduce asthma attacks"
    assert name == "does-vitamin-d-reduce-asthma-attacks.zip"
    assert f"{root}/README.txt" in files and f"{root}/summary.csv" in files
    first = f"{root}/01 - Vitamin D a trial in children"
    assert files[f"{first}/paper.pdf"].startswith(b"%PDF-")
    assert files[f"{first}/tables/table-01.csv"].decode().splitlines() == ["Group,N", "A,40"]
    assert files[f"{first}/figures/fig1.png"] == b"\x89PNG fake"
    assert f"{root}/02 - Paywalled paper/where-to-get-this-paper.txt" in files


def test_an_unverified_value_is_written_as_withheld_never_as_the_value(assets):
    _, data = build_export(_session(), client=_client(), assets_dir=assets)
    files = _unzip(data)
    md = next(v.decode() for k, v in files.items() if k.endswith("01 - Vitamin D a trial in children/summary.md"))
    assert "**Main result:** fewer attacks" in md
    assert "**Effect size:** withheld (quote not found)" in md
    assert "made up" not in md
    assert "long-term effects remain unknown" in md
    assert "We recruited 80 children." in md
    rows = list(csv.DictReader(io.StringIO(next(v.decode() for k, v in files.items() if k.endswith("summary.csv")))))
    assert rows[0]["Effect size"] == "withheld (quote not found)"
    assert rows[0]["PDF saved"] == "yes" and rows[1]["PDF saved"] == "no"


def test_a_bot_check_page_is_not_saved_as_a_pdf(assets):
    _, data = build_export(_session(), client=_client(pdf_ok=False), assets_dir=assets)
    files = _unzip(data)
    assert not any(k.endswith("paper.pdf") for k in files)
    note = next(v.decode() for k, v in files.items() if k.endswith("01 - Vitamin D a trial in children/where-to-get-this-paper.txt"))
    assert "refused a scripted download" in note
    assert "https://example.org/W1" in note


def test_europe_pmcs_renderer_is_tried_last():
    urls = pdf_candidates({"work_id": "https://openalex.org/W1", "pmcid": "PMC1"}, client=_client())
    assert urls == ["https://publisher.example/w1.pdf", "https://europepmc.org/articles/PMC1?pdf=render"]


def test_data_json_carries_the_abstract_and_full_text(assets):
    _, data = build_export(_session(), client=_client(), assets_dir=assets)
    files = _unzip(data)
    payload = json.loads(next(v for k, v in files.items() if k.endswith("01 - Vitamin D a trial in children/data.json")))
    assert payload["abstract"] == "An abstract."
    assert payload["full_text"]["tables"][0]["label"] == "Table 1"


def test_the_gaps_a_paper_states_in_its_body_reach_the_folder(assets):
    """The researcher sees them on screen; the export must keep them.

    These are what the abstract stage cannot see, so an export without
    them loses the newest thing the tool found.
    """
    name, blob = build_export(_session(), client=assets, fetch_pdfs=False)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        summary = next(n for n in zf.namelist() if n.endswith("summary.md") and "01 - " in n)
        text = zf.read(summary).decode()
        rows = list(csv.reader(io.StringIO(
            zf.read(next(n for n in zf.namelist() if n.endswith("summary.csv"))).decode()
        )))

    assert "## Gaps the authors state in this paper" in text
    assert "Further research is needed to establish whether the effect persists." in text
    assert "Long-term effect is unknown · Discussion" in text

    header, first = rows[0], rows[1]
    assert "Gaps stated in the body" in header
    body_column = header.index("Gaps stated in the body")
    assert "Further research is needed" in first[body_column]
    # The abstract-level gap keeps its own column, since they answer
    # different questions.
    assert "long-term effects remain unknown" in first[header.index("Gap stated in the abstract")]


def test_a_paper_with_no_stated_gap_says_so_rather_than_leaving_a_hole(assets):
    session = _session()
    paper = next(p for p in session["fulltext"]["papers"] if p.get("found"))
    paper["gaps"] = []
    paper["gaps_note"] = "none_stated"
    _name, blob = build_export(session, client=assets, fetch_pdfs=False)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        summary = next(n for n in zf.namelist() if n.endswith("summary.md") and "01 - " in n)
        text = zf.read(summary).decode()
    assert "None stated in the body." in text


def test_only_cached_assets_are_copied(tmp_path):
    session = _session()
    session["fulltext"]["papers"][1]["figures"][0]["images"][0]["download_url"] = "/etc/passwd"
    _, data = build_export(session, client=_client(), assets_dir=tmp_path)
    assert not any("/figures/" in k for k in _unzip(data))


def test_nothing_read_in_full_means_nothing_to_export():
    with pytest.raises(ValueError):
        build_export({"query": "q", "papers": [], "fulltext": None}, fetch_pdfs=False)
