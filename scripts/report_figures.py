"""Draw the two diagrams the WIP and final reports use.

Separate from ``build_report.py`` because the figures change far less often
than the prose, and regenerating them on every report build would make the
build slow for no reason. Writes PNGs into ``reports/figures/``.

    python scripts/report_figures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "reports" / "figures"

PROD, SVC, ADP, EVAL, EXT = "#d7e8e4", "#eef3ea", "#f3ece0", "#e6e2f0", "#f0f0ee"
HUMAN, GATE = "#f6dfd2", "#cfe3dc"
INK = "#15211f"
EDGE = "#33413f"


def box(ax, x, y, w, h, label, fc, fs=8.5, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012", fc=fc, ec=EDGE, lw=1.0))
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=fs,
            color=INK, weight="bold" if bold else "normal", linespacing=1.35)


def arrow(ax, p, q, col=EDGE, ls="-"):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=11, lw=1.0,
                                 color=col, linestyle=ls, shrinkA=1, shrinkB=1))


def architecture(commit: str) -> Path:
    """Figure 1. Deliberately shows the product path and the evidence path as
    separate stacks, because that separation is the point the report makes."""
    fig, ax = plt.subplots(figsize=(9.6, 6.8))
    ax.set_xlim(0, 10), ax.set_ylim(0, 7.4), ax.axis("off")
    ax.text(5, 7.15, f"Figure 1. System architecture as delivered (commit {commit})",
            ha="center", fontsize=10.5, weight="bold", color=INK)

    box(ax, 0.3, 6.05, 3.1, 0.72, "Streamlit app — one page\napp/Home.py", PROD, 9, True)
    box(ax, 3.75, 6.05, 2.6, 0.72, "FastAPI\n11 product routes", PROD, 9, True)
    box(ax, 6.7, 6.05, 3.0, 0.72, "Google OIDC\napi/auth.py", PROD, 9)

    for x, lab in [(0.3, "suggest.py\nquestion → papers"),
                   (2.6, "screen.py\nask → validate → verify"),
                   (4.9, "gap.py\nstated gap?"),
                   (7.2, "extract_fulltext.py\n5 body fields")]:
        box(ax, x, 4.85, 2.1, 0.78, lab, SVC, 8)
    box(ax, 0.3, 3.9, 2.1, 0.6, "export.py\nsummary · CSV", SVC, 8)
    box(ax, 2.6, 3.9, 2.1, 0.6, "verify.py\nTHE span verifier", "#bcd9d0", 8.5, True)
    box(ax, 4.9, 3.9, 2.1, 0.6, "fulltext_categories.py\n8 categories", SVC, 8)
    box(ax, 7.2, 3.9, 2.1, 0.6, "discover.py\n_discover boundary", SVC, 8)

    for x, lab in [(0.3, "llm.py\nMock·Gemini\nOllama·OpenAI"), (2.6, "embed.py\nSPECTER2"),
                   (4.9, "fulltext.py\nEurope PMC JATS"), (7.2, "db.py\nSQLite v4 · FTS5")]:
        box(ax, x, 2.85, 2.1, 0.72, lab, ADP, 8)
    for x, lab in [(0.3, "OpenAlex (CC0)"), (2.6, "HuggingFace"),
                   (4.9, "Europe PMC"), (7.2, "SYNERGY")]:
        box(ax, x, 1.85, 2.1, 0.6, lab, EXT, 8)

    box(ax, 0.3, 0.42, 4.4, 0.95,
        "slr/eval — THE EVIDENCE (23 modules)\nharness · metrics · ablation · typology\n"
        "gap_recall · agreement · asreview · fulltext_harness", EVAL, 8, True)
    box(ax, 5.1, 0.42, 4.6, 0.95,
        "runs/ — 80 run directories\nconfig + metrics + run.json + git_sha\n"
        "reports/results.md · run_index.md", EVAL, 8, True)

    arrow(ax, (3.4, 6.41), (3.75, 6.41)); arrow(ax, (6.35, 6.41), (6.7, 6.41))
    arrow(ax, (1.85, 6.05), (1.35, 5.63)); arrow(ax, (4.6, 6.05), (3.65, 5.63))
    arrow(ax, (5.3, 6.05), (5.95, 5.63)); arrow(ax, (5.8, 6.05), (8.25, 5.63))
    for x in (3.65, 5.95, 8.25):
        arrow(ax, (x, 4.85), (3.65, 4.5))
    arrow(ax, (1.35, 4.85), (1.35, 4.5))
    for x in (1.35, 3.65, 5.95, 8.25):
        arrow(ax, (x, 3.9), (x, 3.57), col="#8a9290")
        arrow(ax, (x, 2.85), (x, 2.45), col="#8a9290", ls=":")
    arrow(ax, (4.7, 0.9), (5.1, 0.9))
    ax.text(5, 0.12, "Solid: product request path.  Dotted: external data sources.  "
            "The product imports nothing from slr/eval — the evidence path is separate by design.",
            ha="center", fontsize=7.6, color="#5a6360", style="italic")

    path = OUT / "fig1_architecture.png"
    plt.tight_layout(); plt.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close()
    return path


def process_flow() -> Path:
    """Figure 2. Peach marks every step where a human decides, because the
    report's claim is that the path is deliberately not fully automatic."""
    fig, ax = plt.subplots(figsize=(9.6, 6.9))
    ax.set_xlim(0, 10), ax.set_ylim(0, 7.4), ax.axis("off")
    ax.text(5, 7.18, "Figure 2. Process flow, one research question end to end",
            ha="center", fontsize=10.5, weight="bold", color=INK)

    for y, lab, fc, bold in [
        (6.35, "1  Researcher types a research question", HUMAN, True),
        (5.55, "2  OpenAlex search — only records with a redistributable abstract (~50% of the index)", PROD, False),
        (4.75, "3  SPECTER2 ranks the pool by closeness to the question", PROD, False),
        (3.95, "4  Model screens top n: relevant? + does the abstract state a gap?\n"
               "(the question itself becomes screen_v1's inclusion rule)", PROD, False),
    ]:
        box(ax, 0.5, y, 9.0, 0.62 if "\n" not in lab else 0.72, lab, fc, 8.6, bold)

    box(ax, 0.5, 3.0, 9.0, 0.68,
        "5  SPAN VERIFIER — is the quoted sentence in the source, verbatim after normalisation?",
        GATE, 8.8, True)
    box(ax, 0.5, 2.16, 4.35, 0.62, "Verified → shown as the system's call", PROD, 8.4)
    box(ax, 5.15, 2.16, 4.35, 0.62, "Not found → WITHHELD, referred to the human", HUMAN, 8.4, True)
    box(ax, 0.5, 1.32, 9.0, 0.62,
        "6  Researcher picks up to 5 papers to read in full   ← human decides what is worth the deeper read",
        HUMAN, 8.6, True)
    box(ax, 0.5, 0.48, 9.0, 0.62,
        "7  Europe PMC full text → 5 fields + 8 categories, every value gated by the same verifier → export",
        PROD, 8.6)

    for a, b in [(6.35, 6.17), (5.55, 5.37), (4.75, 4.67), (3.95, 3.68), (1.32, 1.10)]:
        arrow(ax, (5, a), (5, b))
    for x in (2.7, 7.3):
        arrow(ax, (x, 3.0), (x, 2.78)); arrow(ax, (x, 2.16), (x, 1.94))
    ax.text(5, 0.22, "Peach = human in the loop.  Teal = the verification gate.  "
            "No figure on this path is scored: there is no ground truth for a question typed a minute ago.",
            ha="center", fontsize=7.6, color="#5a6360", style="italic")

    path = OUT / "fig2_process_flow.png"
    plt.tight_layout(); plt.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close()
    return path


def main(argv: list[str] | None = None) -> int:
    import subprocess
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                         text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        commit = "unknown"
    for p in (architecture(commit), process_flow()):
        print(f"  wrote {p.relative_to(OUT.parents[1])}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
