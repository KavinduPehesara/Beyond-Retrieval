"""Beyond Retrieval — LLM-supported literature review and gap detection.

Package layout mirrors the architecture in the proposal:

    slr.config      configuration loading and hashing
    slr.db          SQLite schema and connection
    slr.services    ingest, retrieve, screen  (no knowledge of API or UI)
    slr.adapters    LLM providers behind one interface
    slr.eval        metrics and the command-line harness

Nothing in ``slr.services`` imports from an API or UI layer. That is what
lets the evaluation harness run headlessly, and what stops the demonstrated
system diverging from the measured one.
"""

__version__ = "0.1.0"
