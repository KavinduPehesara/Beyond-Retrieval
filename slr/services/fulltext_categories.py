"""Eight-category coverage with exact source passages, not inferred claims.

Heading/keyword selection is deliberately labelled as source evidence. It
does not claim to understand a method, identify every result, or validate
the semantics of an LLM-extracted value.
"""
from __future__ import annotations

import re

from slr.adapters.fulltext import FullText
from slr.adapters.fulltext_assets import fetch_assets, find_asset

CATEGORIES = (
    ("data_tables", "Data tables"), ("heat_maps", "Heat maps"),
    ("graphs_charts", "Graphs and charts"), ("statistical_results", "Statistical results"),
    ("methods", "Methods"), ("equations_models", "Equations and models"),
    ("supplementary_files", "Supplementary files"), ("limitations", "Limitations"),
)


def unavailable_categories(note: str) -> list[dict]:
    return [{"key": key, "label": label, "status": "source_unavailable", "count": 0, "note": note}
            for key, label in CATEGORIES]


def source_evidence(paper: FullText) -> dict[str, list[dict]]:
    evidence: dict[str, list[dict]] = {key: [] for key, _ in CATEGORIES}
    for section in paper.sections:
        heading = section.title or "Untitled section"
        methods = bool(re.search(r"method|procedure|design|participant|recruit|intervention|measurement|analysis", heading, re.I))
        limitation_section = bool(re.search(r"limitation|weakness|caveat|future", heading, re.I))
        for paragraph in section.text.splitlines():
            if not paragraph.strip():
                continue
            # Whole paragraphs retain contiguous evidence and decimal numbers.
            item = {"source": heading, "quote": paragraph, "kind": "source_passage"}
            if methods:
                evidence["methods"].append(item)
            if re.search(r"confidence interval|\bCI\b|\bp\s*[<=>]|\bP value|odds ratio|risk ratio|hazard ratio|mean difference|test statistic|standard deviation|regression coefficient", paragraph, re.I):
                evidence["statistical_results"].append(item)
            if limitation_section or re.search(r"\blimitation[s]?\b|\blimited by\b|\bwe (?:did not|could not|cannot)\b|\bfuture (?:studies|research|work)\b", paragraph, re.I):
                evidence["limitations"].append(item)
            if re.search(r"\bmodel\b|\bequation\b|\bparameter\b", paragraph, re.I):
                evidence["equations_models"].append(item)
    return evidence


def enrich_fulltext(paper: FullText, *, include_assets: bool = False, asset_loader=None) -> dict:
    """Shared by interactive full-text routes. No benchmark tables are written."""
    evidence = source_evidence(paper)
    assets = {"status": "not_requested", "note": "Images and attachments were not requested.", "files": []}
    if include_assets and paper.pmcid:
        assets = (asset_loader or fetch_assets)(paper.pmcid)
    figures = []
    matched = set()
    for figure in paper.figures:
        value = figure.as_dict()
        images = []
        for ref in figure.asset_refs:
            asset = find_asset(ref, assets["files"])
            if asset and asset.get("asset_id") and asset.get("media_type", "").startswith("image/"):
                images.append(asset)
                matched.add(asset["name"])
        value["images"] = images
        value["analysis_status"] = "needs_human_review"
        figures.append(value)
    supplements = []
    for supplement in paper.supplements:
        asset = find_asset(supplement["asset_ref"], assets["files"])
        value = {**supplement, "status": "source_unavailable", "note": assets["note"] or "Referenced file not present in the returned archive."}
        if asset:
            value.update(asset)
            matched.add(asset["name"])
        supplements.append(value)
    # Keep every unmatched archive file accessible; never silently discard it.
    for asset in assets["files"]:
        if asset["name"] not in matched:
            supplements.append({"label": asset["name"], "caption": "Archive file (not matched to a main figure)", **asset})
    counts = {
        "data_tables": len(paper.tables), "heat_maps": sum(f.kind == "heat_map" for f in paper.figures),
        "graphs_charts": sum(f.kind != "heat_map" for f in paper.figures),
        "statistical_results": len(evidence["statistical_results"]), "methods": len(evidence["methods"]),
        "equations_models": len(paper.equations) + len(evidence["equations_models"]),
        "supplementary_files": len(supplements), "limitations": len(evidence["limitations"]),
    }
    coverage = []
    for key, label in CATEGORIES:
        count = counts[key]
        status = "extracted" if count else "not_found"
        note = "Source content retrieved; correctness and completeness require reviewer assessment."
        if paper.is_fragment:
            note = "Only a source fragment was retrieved; missing content cannot be assessed."
            if not count:
                status = "source_unavailable"
        if key in ("heat_maps", "graphs_charts"):
            status = "needs_human_review" if count else status
            note = "Classified by caption only. Original images and author descriptions are shown when available; plotted values are not digitized."
        elif key == "supplementary_files":
            statuses = {s["status"] for s in supplements}
            status = ("extracted" if "extracted" in statuses else
                      "needs_human_review" if count and statuses - {"source_unavailable"} else
                      "source_unavailable" if count else assets["status"])
            if status == "not_requested":
                status = "source_unavailable"
            previewed = sum(s["status"] == "extracted" for s in supplements)
            note = assets["note"] or f"{previewed} of {len(supplements)} files previewed. Previews may be truncated; check each file's status."
        elif key in ("methods", "statistical_results", "limitations", "equations_models"):
            note = "Heading/keyword-selected source passages; not a complete semantic extraction. Review each passage in context."
        coverage.append({"key": key, "label": label, "status": status, "count": count, "note": note})
    return {"coverage": coverage, "evidence": evidence, "figures": figures,
            "supplements": supplements, "equation_details": paper.equation_details,
            "source_url": f"https://europepmc.org/articles/{paper.pmcid}" if paper.pmcid else None,
            "assets_note": assets["note"]}
