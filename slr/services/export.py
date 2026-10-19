"""Package a research project as a folder the researcher keeps.

One ZIP, which unpacks to:

    Beyond Retrieval - <question>/
        README.txt         what the question was, and how to read the rest
        summary.csv        one row per selected paper: relevance, full-text fields, gap
        01 - <title>/
            paper.pdf      when an open-access PDF could be downloaded
            where-to-get-this-paper.txt   when it could not, and why
            summary.md     everything below, readable
            data.json      the same, machine-readable
            tables/        each table as CSV, exactly as the publisher printed it
            figures/       figure images, when the publisher's file had them
            supplementary/ supplementary files, when cached

Nothing here is new analysis. Every value was already produced, and verified
or withheld, by the suggest and full-text stages; this only writes it down,
with the same rule: a value whose quote did not verify is written as
"withheld", never as the value.

PDFs come from open-access links listed by OpenAlex and Europe PMC. Europe
PMC's own PDF renderer refuses scripted downloads (403 behind a bot check,
observed 20 October 2026), so publisher links are tried first and the
renderer last.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path

import httpx

from slr.adapters import fulltext_assets

MAX_PDF_BYTES = 50_000_000
MAX_PDF_TRIES = 4
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 BeyondRetrieval/1.0"
)

FULLTEXT_FIELDS = [
    ("primary_outcome", "Main result"),
    ("effect_size", "Effect size"),
    ("statistical_methods", "Method"),
    ("sample_characteristics", "Sample"),
    ("limitations", "Limitations"),
]

RELEVANCE_TEXT = {
    "relevant": "Addresses your question",
    "check": "Check it yourself",
    "not_relevant": "Probably off-topic",
}


def safe_name(text: str | None, limit: int = 60) -> str:
    """A file or folder name every OS accepts."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", text or "")
    name = " ".join(name.split())[:limit].rstrip(" .")
    return name or "untitled"


def relevance_label(paper: dict) -> str:
    """Relevant only when the model said include *and* its quote verified."""
    d = paper.get("decision") or {}
    if not d.get("span_verified"):
        return "check"
    return "relevant" if d.get("status") == "include" else "not_relevant"


def field_text(item: dict | None) -> str:
    if not item:
        return ""
    if item.get("status") == "verified":
        return item.get("value") or ""
    if item.get("status") == "not_stated":
        return "not stated"
    return "withheld (quote not found)"


def pmcid_of(paper: dict) -> str | None:
    if paper.get("pmcid"):
        return paper["pmcid"]
    match = re.search(r"\bPMC\d+\b", paper.get("note") or "")
    return match.group(0) if match else None


# ---------------------------------------------------------------------------
# PDFs
# ---------------------------------------------------------------------------


def pdf_candidates(paper: dict, *, client: httpx.Client) -> list[str]:
    """Open-access PDF links for one paper, most likely to work first."""
    urls: list[str] = []
    work = (paper.get("work_id") or "").rsplit("/", 1)[-1]
    if re.fullmatch(r"W\d+", work):
        try:
            r = client.get(
                f"https://api.openalex.org/works/{work}",
                params={"select": "best_oa_location,locations"},
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
            for loc in [data.get("best_oa_location") or {}, *(data.get("locations") or [])]:
                if loc and loc.get("pdf_url"):
                    urls.append(loc["pdf_url"])
        except (httpx.HTTPError, ValueError):
            pass
    pmcid = pmcid_of(paper)
    if pmcid:
        try:
            r = client.get(
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                params={"query": f"PMCID:{pmcid}", "resultType": "core", "format": "json"},
                timeout=20,
            )
            r.raise_for_status()
            results = r.json().get("resultList", {}).get("result", [])
            for entry in (results[0].get("fullTextUrlList", {}).get("fullTextUrl", []) if results else []):
                if entry.get("documentStyle") == "pdf" and entry.get("availability") == "Open access":
                    urls.append(entry["url"])
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            pass
    seen, ordered = set(), []
    # Europe PMC's renderer last: it refuses scripted requests.
    for url in sorted(urls, key=lambda u: "europepmc.org" in u):
        if url.startswith("https://") and url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def download_pdf(paper: dict, *, client: httpx.Client) -> tuple[bytes | None, str]:
    """The paper's PDF and where it came from, or None and why not."""
    candidates = pdf_candidates(paper, client=client)
    if not candidates:
        return None, "No open-access PDF is listed for this paper. It is probably behind a paywall."
    for url in candidates[:MAX_PDF_TRIES]:
        try:
            with client.stream("GET", url, timeout=60, follow_redirects=True) as r:
                if r.status_code != 200:
                    continue
                data = b""
                for chunk in r.iter_bytes():
                    data += chunk
                    if len(data) > MAX_PDF_BYTES:
                        break
            # A login page or a bot check is served as 200 HTML more often
            # than not, so trust the bytes, not the status or the header.
            if data.startswith(b"%PDF-") and len(data) <= MAX_PDF_BYTES:
                return data, url
        except httpx.HTTPError:
            continue
    return None, (
        "Open-access PDF links exist, but none could be downloaded automatically "
        "(the publisher refused a scripted download). Open the link below in your browser."
    )


# ---------------------------------------------------------------------------
# The folder
# ---------------------------------------------------------------------------


def _csv(rows: list[list]) -> str:
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return out.getvalue()


def _asset_path(download_url: str | None, assets_dir: Path) -> Path | None:
    """Map an app asset URL back to its cached file, refusing anything else."""
    match = re.fullmatch(r"/fulltext/assets/(PMC\d+)/([0-9a-f]{64})", download_url or "")
    if not match:
        return None
    path = assets_dir / match.group(1) / match.group(2)
    return path if path.is_file() else None


def paper_markdown(rank: int, suggestion: dict, paper: dict, pdf_note: str) -> str:
    lines = [f"# {paper.get('title') or paper['work_id']}", ""]
    if suggestion.get("year"):
        lines.append(f"Year: {suggestion['year']}")
    if suggestion.get("doi"):
        lines.append(f"DOI: {suggestion['doi']}")
    if suggestion.get("source_url"):
        lines.append(f"Link: {suggestion['source_url']}")
    lines += [f"Suggestion rank: #{rank}", f"PDF: {pdf_note}", ""]

    lines.append("## Relevance to your question")
    lines.append(RELEVANCE_TEXT[relevance_label(suggestion)])
    if suggestion.get("relevance") is not None:
        lines.append(f"Similarity to the question: {suggestion['relevance']:.2f}")
    d = suggestion.get("decision") or {}
    if d.get("quote") and d.get("span_verified"):
        lines.append(f'Why: "{d["quote"]}" (found word for word in the abstract)')
    lines.append("")

    gap = suggestion.get("gap") or {}
    lines.append("## Research gap the authors state")
    lines.append(f'"{gap["quote"]}"' if gap.get("status") == "gap_stated" else "None stated in the abstract.")
    lines.append("")

    lines.append("## From the full paper")
    lines.append(paper.get("note") or ("Full text found." if paper.get("found") else "No full text."))
    lines.append("")
    for field, label in FULLTEXT_FIELDS:
        item = paper.get(field)
        if not item:
            continue
        lines.append(f"**{label}:** {field_text(item)}")
        if item.get("status") == "verified" and item.get("quote"):
            lines.append(f'> {item["quote"]}')
        lines.append("")

    coverage = paper.get("coverage") or []
    if coverage:
        lines.append("## What the paper contains, by category")
        evidence = paper.get("evidence") or {}
        for category in coverage:
            lines.append(f"### {category.get('label')}")
            lines.append(f"{category.get('status')} · {category.get('count', 0)} items. {category.get('note', '')}")
            for item in evidence.get(category.get("key"), [])[:8]:
                lines.append(f"- *{item.get('source')}*: {item.get('quote')}")
            lines.append("")

    tables = paper.get("tables") or []
    if tables:
        lines.append(f"## Tables ({len(tables)}), saved as CSV in tables/")
        for i, t in enumerate(tables, 1):
            lines.append(f"- table-{i:02d}.csv: {' · '.join(x for x in (t.get('label'), t.get('caption')) if x)}")
        lines.append("")
    figures = paper.get("figures") or []
    if figures:
        lines.append(f"## Figures ({len(figures)})")
        for f in figures:
            lines.append(f"- {' · '.join(x for x in (f.get('label'), f.get('caption')) if x)}")
            for mention in f.get("mentions") or []:
                lines.append(f'  - "{mention}"')
        lines.append("")
    return "\n".join(lines)


def build_export(
    session: dict,
    *,
    client: httpx.Client | None = None,
    assets_dir: Path | None = None,
    fetch_pdfs: bool = True,
) -> tuple[str, bytes]:
    """(file name, ZIP bytes) for the papers the researcher read in full."""
    assets_dir = assets_dir or fulltext_assets.ASSETS_DIR
    fulltext = (session.get("fulltext") or {}).get("papers") or []
    if not fulltext:
        raise ValueError("No papers have been read in full yet, so there is nothing to export.")

    suggestions = session.get("papers") or []
    by_id = {p["work_id"]: p for p in suggestions}
    rank_of = {p["work_id"]: i for i, p in enumerate(suggestions, 1)}
    papers = sorted(fulltext, key=lambda p: rank_of.get(p["work_id"], 999))

    question = session.get("query") or "research"
    root = safe_name(f"Beyond Retrieval - {question}", 80)
    owns_client = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT})

    summary = [["Rank", "Folder", "Title", "Year", "DOI", "Relevance", "Similarity", "Full text",
                "PDF saved", *(label for _, label in FULLTEXT_FIELDS), "Stated research gap"]]
    buffer = io.BytesIO()
    try:
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for index, paper in enumerate(papers, 1):
                s = by_id.get(paper["work_id"], {})
                rank = rank_of.get(paper["work_id"], index)
                folder = f"{root}/{index:02d} - {safe_name(paper.get('title') or s.get('title'))}"

                pdf, pdf_source = (download_pdf({**s, **paper}, client=client) if fetch_pdfs
                                   else (None, "PDF download was not requested."))
                if pdf:
                    zf.writestr(f"{folder}/paper.pdf", pdf)
                    pdf_note = f"saved as paper.pdf, from {pdf_source}"
                else:
                    link = s.get("source_url") or s.get("doi") or ""
                    zf.writestr(f"{folder}/where-to-get-this-paper.txt",
                                f"{pdf_source}\n\nTitle: {paper.get('title')}\nLink: {link}\nDOI: {s.get('doi') or ''}\n")
                    pdf_note = pdf_source

                zf.writestr(f"{folder}/summary.md", paper_markdown(rank, s, paper, pdf_note))
                zf.writestr(f"{folder}/data.json", json.dumps(
                    {"suggestion": {k: v for k, v in s.items() if k != "abstract"},
                     "abstract": s.get("abstract"), "full_text": paper},
                    ensure_ascii=False, indent=2))

                for i, table in enumerate(paper.get("tables") or [], 1):
                    if table.get("rows"):
                        zf.writestr(f"{folder}/tables/table-{i:02d}.csv", _csv(table["rows"]))
                for figure in paper.get("figures") or []:
                    for image in figure.get("images") or []:
                        path = _asset_path(image.get("download_url"), assets_dir)
                        if path:
                            zf.write(path, f"{folder}/figures/{safe_name(image.get('name') or path.name, 80)}")
                for supplement in paper.get("supplements") or []:
                    path = _asset_path(supplement.get("download_url"), assets_dir)
                    if path:
                        name = supplement.get("name") or supplement.get("label") or path.name
                        zf.write(path, f"{folder}/supplementary/{safe_name(name, 80)}")

                gap = s.get("gap") or {}
                summary.append([
                    rank, folder.rsplit("/", 1)[-1], paper.get("title"), s.get("year"), s.get("doi"),
                    RELEVANCE_TEXT[relevance_label(s)] if s else "",
                    f"{s['relevance']:.2f}" if s.get("relevance") is not None else "",
                    "yes" if paper.get("found") else "no", "yes" if pdf else "no",
                    *(field_text(paper.get(f)) for f, _ in FULLTEXT_FIELDS),
                    gap.get("quote") if gap.get("status") == "gap_stated" else "",
                ])

            zf.writestr(f"{root}/summary.csv", _csv(summary))
            zf.writestr(f"{root}/README.txt", (
                f"Research question: {question}\n"
                f"Exported: {date.today().isoformat()}\n"
                f"Papers: {len(papers)}\n\n"
                "Each numbered folder is one paper you selected. summary.md is the readable "
                "version; data.json holds the same data for other tools.\n\n"
                "Every value extracted by the model was checked against the paper: it is shown "
                "only when its supporting quote was found word for word. 'withheld' means the "
                "model proposed a value but its quote was not found, so the value is not given. "
                "Tables and figures come straight from the publisher's file.\n\n"
                "A missing paper.pdf means no open-access PDF could be downloaded; "
                "where-to-get-this-paper.txt says why and links to the paper.\n"
            ))
    finally:
        if owns_client:
            client.close()
    return safe_name(question, 50).replace(" ", "-").lower() + ".zip", buffer.getvalue()
