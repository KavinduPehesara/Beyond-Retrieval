"""Evidence and coverage for all eight full-text source categories."""
from __future__ import annotations

import csv
import io
import json

import streamlit as st
from api_client import API_URL

STATUS = {"extracted": "Extracted", "not_found": "Not found in retrieved content",
          "source_unavailable": "Source unavailable", "verification_failed": "Verification failed",
          "needs_human_review": "Needs human review", "unsupported": "Unsupported format"}


def _csv(rows):
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return out.getvalue()


def _grid(table):
    """Align merged cells while retaining every source row, including headers."""
    result, occupied = [], {}
    spans = table.get("cell_spans") or []
    for row_index, row in enumerate(table.get("rows") or []):
        cells, column = {}, 0
        for index, value in enumerate(row):
            while (row_index, column) in occupied:
                cells[column] = ""
                column += 1
            span = spans[row_index][index] if row_index < len(spans) and index < len(spans[row_index]) else {}
            try:
                height = min(max(int(span.get("rowspan", 1)), 1), 100)
                width = min(max(int(span.get("colspan", 1)), 1), 100)
            except (TypeError, ValueError):
                height = width = 1
            cells[column] = value
            for r in range(row_index, row_index + height):
                for c in range(column, column + width):
                    occupied[r, c] = True
                    if r == row_index and c != column:
                        cells[c] = ""
            column += width
        for r, c in occupied:
            if r == row_index:
                cells.setdefault(c, "")
        result.append(cells)
    width = max((max(row, default=-1) + 1 for row in result), default=0)
    return [[row.get(c, "") for c in range(width)] for row in result]


def _fields(paper, names):
    for name, label in names:
        item = paper.get(name)
        if not item:
            continue
        if item["status"] == "verified":
            st.markdown(f"**{label}:** {item['value']}")
            st.caption(f"Quote matched the source: “{item.get('quote', '')}”")
        elif item["status"] in ("unverified", "failed", "error"):
            st.markdown(f"**{label}:** Verification failed — answer withheld")
        else:
            st.caption(f"{label}: Not stated in the text shown to the model. Check source coverage.")


def _passages(paper, key):
    items = paper.get("evidence", {}).get(key, [])
    if items:
        st.caption("Exact source passages selected by section heading or keywords. Selection does not establish the meaning or completeness of an answer.")
    for item in items[:8]:
        st.markdown(f"**Source: {item['source']}**")
        st.text(item["quote"])
    if len(items) > 8:
        st.caption(f"Showing 8 of {len(items)} passages. Download the evidence JSON for all passages.")


def _figures(paper, heat_maps):
    figures = [f for f in paper.get("figures", []) if (f.get("kind") == "heat_map") == heat_maps]
    for figure in figures:
        st.markdown(f"**{figure.get('label') or 'Figure'}** — {figure.get('caption') or 'No caption'}")
        for image in figure.get("images", []):
            st.image(API_URL + image["download_url"], caption="Original source image — interpretation requires review.", use_container_width=True)
            st.link_button("Download original image", API_URL + image["download_url"])
        if not figure.get("images"):
            st.caption("Image file unavailable; caption and references only.")
        for mention in figure.get("mentions", []):
            st.text(mention)
    st.caption("Heat maps are identified from captions only. Pixel interpretation and plotted-value digitization are not performed.")


def render_categories(paper):
    key_prefix = str(paper.get("fulltext_ui_key") or paper.get("work_id") or paper.get("title") or "fulltext")
    with st.expander("From the full paper", expanded=True):
        st.caption(paper.get("fulltext_note") or paper.get("note") or "")
        if paper.get("source_url"):
            st.link_button("Open source paper", paper["source_url"])
        coverage = paper["coverage"]
        with st.popover("View source coverage"):
            for category in coverage:
                status = STATUS.get(category["status"], category["status"])
                st.markdown(f"**{category['label']}** — {status} · {category['count']} items")
        st.download_button("Download all source evidence (JSON)", json.dumps(paper, ensure_ascii=False, indent=2),
                           "fulltext-evidence.json", "application/json", key=key_prefix + "-evidence")
        for index, category in enumerate(coverage, 1):
            key = category["key"]
            st.subheader(f"{index}. {category['label']}")
            st.caption(f"{STATUS.get(category['status'], category['status'])} · {category['note']}")
            if key == "data_tables":
                for table_index, table in enumerate(paper.get("tables", [])):
                    st.markdown(f"**{table.get('label') or 'Table'}** — {table.get('caption') or ''}")
                    rows = _grid(table)
                    if rows:
                        st.dataframe(rows, hide_index=True, use_container_width=True)
                        st.download_button("Download table CSV", _csv(rows), f"table-{table_index + 1}.csv", "text/csv",
                                           key=f"{key_prefix}-table-{table_index}")
                    for footnote in table.get("footnotes", []):
                        st.caption(footnote)
                    st.caption("Source header rows are retained. Merged-cell values appear once; covered cells are blank. Units remain in source labels and cells.")
            elif key in ("heat_maps", "graphs_charts"):
                _figures(paper, key == "heat_maps")
            elif key == "statistical_results":
                _fields(paper, [("primary_outcome", "Main result"), ("effect_size", "Effect size")])
                _passages(paper, key)
                st.caption("Additional numerical results may appear in the data tables above; table cells are kept separate from prose evidence.")
            elif key == "methods":
                _fields(paper, [("statistical_methods", "Statistical method"), ("sample_characteristics", "Sample")])
                _passages(paper, key)
            elif key == "equations_models":
                details = paper.get("equation_details") or [{"text": e} for e in paper.get("equations", [])]
                for equation_index, equation in enumerate(details):
                    if equation.get("label"):
                        st.caption(equation["label"])
                    if equation.get("latex"):
                        st.latex(equation["latex"])
                    else:
                        st.code(equation.get("text", ""), language=None)
                    if equation.get("mathml"):
                        st.download_button("Download original MathML", equation["mathml"], f"equation-{equation_index + 1}.xml",
                                           "application/xml", key=f"{key_prefix}-math-{equation_index}")
                _passages(paper, key)
            elif key == "supplementary_files":
                for supplement in paper.get("supplements", []):
                    st.markdown(f"**{supplement.get('label') or supplement.get('name')}**")
                    st.caption(supplement.get("caption") or "")
                    st.caption(f"{STATUS.get(supplement['status'], supplement['status'])}: {supplement.get('note', '')}")
                    if supplement.get("download_url"):
                        st.link_button("Download source file", API_URL + supplement["download_url"])
                    if supplement.get("text"):
                        st.text(supplement["text"][:10000])
                        if len(supplement["text"]) > 10000:
                            st.caption("Text display limited to 10,000 characters. More is included in the evidence JSON.")
                    for table in supplement.get("tables", []):
                        st.caption(table["label"])
                        st.dataframe(table["rows"], hide_index=True, use_container_width=True)
            elif key == "limitations":
                _fields(paper, [("limitations", "Model-extracted limitation")])
                _passages(paper, key)
                st.caption("A failed model answer does not mean limitations are absent. Source passages above allow independent review.")
