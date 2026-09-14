"""Evidence span verification.

This is the mechanism behind the *verifiable* property in RQ1. The model is
required to return a quote from the source; this module checks the quote is
actually there. A decision whose span cannot be found is not trusted and does
not enter the result set — it is routed to a human instead.

The whole trust argument reduces to whether this function is correct, so it is
deliberately small, has no dependencies, and is the most heavily tested thing
in the repository.

Design notes
------------
Verification is *substring matching after normalisation*, not fuzzy matching.
Fuzzy matching would let a paraphrase pass, and a paraphrase is exactly the
failure mode being guarded against — a model that quietly rewords the source
is a model that can quietly invent.

Normalisation only removes differences that are artefacts of transport rather
than of meaning:

* Unicode compatibility normalisation (NFKC), so ligatures and full-width
  characters compare equal to their plain forms.
* Curly quotes and dashes folded to ASCII, because models routinely return
  typographic quotes where the source has straight ones.
* Whitespace collapsed, because line wrapping in the source is not a
  difference in what was said.
* Case folded, because capitalisation at a sentence boundary is not either.

Anything beyond that — dropped words, reordered clauses, synonyms — fails, and
should.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Characters models substitute freely for their ASCII equivalents.
_TRANSLATIONS = str.maketrans(
    {
        "‘": "'",  # left single quote
        "’": "'",  # right single quote
        "‚": "'",
        "‛": "'",
        "“": '"',  # left double quote
        "”": '"',  # right double quote
        "„": '"',
        "′": "'",  # prime
        "″": '"',  # double prime
        "‐": "-",  # hyphen
        "‑": "-",  # non-breaking hyphen
        "‒": "-",  # figure dash
        "–": "-",  # en dash
        "—": "-",  # em dash
        "―": "-",  # horizontal bar
        "−": "-",  # minus sign
        " ": " ",  # non-breaking space
        "…": "...",  # ellipsis
    }
)

_WHITESPACE = re.compile(r"\s+")

# The shortest span we will accept. Below this, a match is not evidence of
# anything — "the" appears in every abstract ever written.
MIN_SPAN_CHARS = 20


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of checking one span against one source."""

    verified: bool
    note: str

    def __bool__(self) -> bool:  # so callers can write `if result:`
        return self.verified


def normalise(text: str) -> str:
    """Fold away differences that are transport artefacts, not meaning."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_TRANSLATIONS)
    text = _WHITESPACE.sub(" ", text)
    return text.strip().casefold()


def verify_span(span: str | None, source: str | None) -> VerificationResult:
    """Return whether ``span`` appears verbatim in ``source``.

    Every rejection carries a reason, because "why did this fail" is a
    reportable number: the distribution of failure notes across a run tells
    you whether the model is hallucinating, truncating, or paraphrasing.
    """
    if span is None or not span.strip():
        return VerificationResult(False, "empty_span")

    if source is None or not source.strip():
        # No abstract to check against. Not the model's fault, but the
        # decision is still unverifiable and must be treated as such.
        return VerificationResult(False, "no_source_text")

    n_span = normalise(span)
    n_source = normalise(source)

    if len(n_span) < MIN_SPAN_CHARS:
        return VerificationResult(
            False, f"span_too_short(<{MIN_SPAN_CHARS}chars)"
        )

    if len(n_span) > len(n_source):
        return VerificationResult(False, "span_longer_than_source")

    if n_span in n_source:
        return VerificationResult(True, "exact_after_normalisation")

    # Distinguish the interesting failure modes from each other. A model that
    # wraps its quote in punctuation is behaving differently from one that
    # invents a sentence, and the report should be able to say which.
    # The stripped span must still meet the minimum length: otherwise a span
    # padded with punctuation passes on a handful of real characters.
    stripped = n_span.strip("\"'.,;:()[] ")
    if (
        len(stripped) >= MIN_SPAN_CHARS
        and stripped != n_span
        and stripped in n_source
    ):
        return VerificationResult(True, "exact_after_punctuation_strip")

    # Did the model quote a real sentence but truncate or extend it? Check
    # whether a substantial prefix matches; useful diagnostically, but NOT
    # accepted as verification.
    probe = n_span[: max(MIN_SPAN_CHARS, len(n_span) // 2)]
    if probe in n_source:
        return VerificationResult(False, "partial_match_only")

    return VerificationResult(False, "not_found")


def source_text(title: str | None, abstract: str | None) -> str:
    """The text a span is allowed to be quoted from.

    Title and abstract, nothing else. Screening operates on abstracts alone
    (Hida et al., 2026 — removing the abstract costs 5.55 percentage points of
    accuracy, while titles and keywords add nothing), so the verifier must not
    silently widen the evidence base beyond what the model was shown.
    """
    return " ".join(p for p in (title, abstract) if p)
