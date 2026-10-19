"""Configuration: one YAML file per experiment, validated on load.

Every run is defined by a config file, and the hash of that file becomes part
of the run directory name. This is what makes rule 2 enforceable — a reported
figure can be traced back to the exact settings that produced it.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

load_dotenv()

# The six SYNERGY reviews in the evaluation subset (proposal, Table 6).
# Inclusion rates deliberately span 0.8% to 21.9%.
SUBSET = {
    "Radjenovic_2013": ("Software engineering", 5935, 48),
    "Smid_2020": ("Computer science", 2627, 27),
    "van_der_Waal_2022": ("Medicine", 1970, 33),
    "Menon_2022": ("Medicine", 975, 74),
    "van_der_Valk_2021": ("Medicine, psychology", 725, 89),
    "Nelson_2002": ("Medicine", 366, 80),
}


class DatasetConfig(BaseModel):
    """Which records to screen."""

    reviews: list[str] = Field(
        ..., description="SYNERGY review names, e.g. ['Smid_2020']"
    )
    max_records: int | None = Field(
        50,
        description=(
            "Cap on records screened per review, taken from the top of the "
            "ranking. Keep this small while developing — it is the cheapest "
            "guard against an accidental full-corpus run. Set to null only for "
            "runs you intend to report. Ingest always loads the full review."
        ),
    )
    seed: int = 42

    @field_validator("reviews")
    @classmethod
    def known_reviews(cls, v: list[str]) -> list[str]:
        unknown = [r for r in v if r not in SUBSET]
        if unknown:
            raise ValueError(
                f"Not in the evaluation subset: {unknown}. "
                f"Allowed: {sorted(SUBSET)}"
            )
        return v


class RankingConfig(BaseModel):
    """The order records are considered in, and the recall target reported at."""

    strategy: Literal["random", "bm25", "dense", "hybrid", "rerank"] = "random"
    query: str | None = Field(
        None,
        description="Ranking query. Defaults to the review's eligibility criteria.",
    )
    recall_target: float = Field(0.95, gt=0.0, le=1.0)
    rrf_k: int = Field(60, description="Reciprocal rank fusion constant, for hybrid/rerank.")
    rerank_top_k: int = Field(
        200, description="How many fused top records the cross-encoder reranks, for rerank only."
    )


class ScreeningConfig(BaseModel):
    """How the language model is called."""

    enabled: bool = Field(
        True,
        description=(
            "false runs a ranking-only baseline: no model calls, no cost, "
            "ranking metrics over the full review."
        ),
    )
    provider: Literal["gemini", "mock", "ollama", "openai"] = "mock"
    # gemini-2.0-flash was shut down on 1 June 2026. 2.5 Flash-Lite is the
    # cheapest model still served; check the deprecations page before a run.
    model: str = "gemini-2.5-flash-lite"
    prompt_version: str = "screen_v1"
    temperature: float = 0.0
    max_output_tokens: int = 512
    max_retries: int = 3
    seed: int | None = Field(
        42,
        description=(
            "Sent to the provider. Best effort only: run-to-run agreement is "
            "measured in week 10, not assumed from this."
        ),
    )


class BudgetConfig(BaseModel):
    """Hard spend ceiling. The run aborts on breach; it does not warn.

    Prices are per million tokens and live in the config rather than the code
    so that a provider price change is a config edit, and so that the price
    assumed by a historical run is recorded alongside its results.
    """

    ceiling_usd: float = 1.0
    # Gemini 2.5 Flash-Lite paid tier, text input, as listed September 2026.
    usd_per_1m_input: float = 0.10
    usd_per_1m_output: float = 0.40


class Config(BaseModel):
    name: str
    dataset: DatasetConfig
    ranking: RankingConfig = RankingConfig()
    screening: ScreeningConfig = ScreeningConfig()
    budget: BudgetConfig = BudgetConfig()

    db_path: Path = Path("data/slr.db")
    runs_dir: Path = Path("runs")
    prompts_dir: Path = Path("prompts")

    cache_enabled: bool = Field(
        True,
        description=(
            "Leave on. The only experiment permitted to bypass the cache is "
            "the week 10 repeated-run measurement, which needs genuine "
            "re-sampling to quantify run-to-run variance."
        ),
    )

    # Populated at load time, not by the file.
    source_path: Path | None = None
    source_text: str | None = None

    @property
    def config_hash(self) -> str:
        """Short stable hash of the config as written on disk."""
        payload = self.source_text or json.dumps(
            self.model_dump(mode="json", exclude={"source_path", "source_text"}),
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:10]

    @property
    def prompt_path(self) -> Path:
        return self.prompts_dir / f"{self.screening.prompt_version}.txt"

    def api_key(self) -> str | None:
        """Read from the environment, never from the config file.

        A key in a config file is a key in git.
        """
        if self.screening.provider == "gemini":
            return os.getenv("GEMINI_API_KEY")
        return None


def load_config(path: str | Path) -> Config:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text) or {}
    cfg = Config(**raw)
    cfg.source_path = path
    cfg.source_text = text
    return cfg


class ExtractConfig(BaseModel):
    """Structured data extraction over a prior screening run's verified
    includes. Deliberately separate from ``Config``: extraction doesn't rank
    or retrieve, it reads another run's output, so ``RankingConfig`` and
    ``DatasetConfig``'s subset validation don't apply.
    """

    name: str
    source_run_id: str = Field(
        ..., description="Screening run to read verified-include decisions from."
    )
    review: str = Field(..., description="SYNERGY review name, e.g. 'Nelson_2002'.")
    provider: Literal["gemini", "mock", "ollama", "openai"] = "mock"
    model: str = "mock-1"
    prompt_version: str = "extract_v1"
    temperature: float = 0.0
    max_output_tokens: int = 512
    max_retries: int = 3
    seed: int | None = 42
    max_records: int | None = Field(
        None, description="Cap on records extracted, taken from the source run's order."
    )

    ceiling_usd: float = 1.0
    usd_per_1m_input: float = 0.10
    usd_per_1m_output: float = 0.40

    db_path: Path = Path("data/slr.db")
    runs_dir: Path = Path("runs")
    prompts_dir: Path = Path("prompts")
    cache_enabled: bool = True

    source_path: Path | None = None
    source_text: str | None = None

    @property
    def config_hash(self) -> str:
        payload = self.source_text or json.dumps(
            self.model_dump(mode="json", exclude={"source_path", "source_text"}),
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:10]

    @property
    def prompt_path(self) -> Path:
        return self.prompts_dir / f"{self.prompt_version}.txt"

    def api_key(self) -> str | None:
        if self.provider == "gemini":
            return os.getenv("GEMINI_API_KEY")
        if self.provider == "openai":
            return os.getenv("OPENAI_API_KEY")
        return None


def load_extract_config(path: str | Path) -> ExtractConfig:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text) or {}
    cfg = ExtractConfig(**raw)
    cfg.source_path = path
    cfg.source_text = text
    return cfg


# --------------------------------------------------------------------------
# Full-text extraction
#
# Separate from ExtractConfig because the input is different in kind.
# Extraction and gap discovery read a prior screening run's verified
# includes -- records already in the `work` table, with ground truth
# beside them. Full-text extraction reads papers named by DOI or PMCID,
# fetched live from Europe PMC, which the evaluation corpus knows nothing
# about. There is no screening run to inherit from and no label to score
# against, so a config that pretended otherwise would invite a figure
# nobody can check.
# --------------------------------------------------------------------------

FULLTEXT_REVIEW = "_fulltext"
"""Review label for live full-text records.

Follows ``_discover``'s precedent exactly: never a real review name, so a
full-text record cannot be mistaken for part of the evaluation corpus, and
``SUBSET`` validation would reject any reported config pointing at it.
"""


class FullTextConfig(BaseModel):
    """Full-text extraction over papers named by DOI or PMCID.

    The supervisor's October note asked that full text be kept as future work
    or a small demonstration, *and* that it be validated against a manually
    annotated reference set with precision, recall and F1 per field. Both of
    those need the run to leave an artefact: until this config existed, full
    text could only be driven through the dashboard, which writes no run
    directory, so under rule 2 no full-text figure was reportable at all.
    """

    name: str
    targets: list[str] = Field(
        default_factory=list,
        description="DOIs or PMCIDs, one paper each. A PMCID is used directly; "
        "anything else is looked up as a DOI, then by title.",
    )
    review: str = FULLTEXT_REVIEW

    provider: Literal["gemini", "mock", "ollama", "openai"] = "mock"
    model: str = "mock-1"
    prompt_version: str = "extract_fulltext_v1"
    temperature: float = 0.0
    max_output_tokens: int = 1024
    max_retries: int = 3
    seed: int | None = 42
    max_records: int | None = None
    max_prompt_chars: int = Field(
        24_000,
        description="How much of a paper's prose the model is shown. Recorded in "
        "the artefact because a field marked 'not stated' may be in what was cut.",
    )

    ceiling_usd: float = 1.0
    usd_per_1m_input: float = 0.10
    usd_per_1m_output: float = 0.40

    db_path: Path = Path("data/slr.db")
    runs_dir: Path = Path("runs")
    prompts_dir: Path = Path("prompts")
    cache_enabled: bool = True

    source_path: Path | None = None
    source_text: str | None = None

    @field_validator("review")
    @classmethod
    def _review_stays_outside_the_corpus(cls, value: str) -> str:
        if value in SUBSET:
            raise ValueError(
                f"review must not be an evaluation-corpus review ({value!r}). "
                f"Live full-text records carry {FULLTEXT_REVIEW!r} so they cannot "
                "be mistaken for benchmark data -- the same boundary '_discover' keeps."
            )
        return value

    @field_validator("targets")
    @classmethod
    def _targets_are_not_blank(cls, value: list[str]) -> list[str]:
        cleaned = [t.strip() for t in value if t and t.strip()]
        if not cleaned:
            raise ValueError("targets must name at least one DOI or PMCID")
        return cleaned

    @property
    def config_hash(self) -> str:
        payload = self.source_text or json.dumps(
            self.model_dump(mode="json", exclude={"source_path", "source_text"}),
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:10]

    @property
    def prompt_path(self) -> Path:
        return self.prompts_dir / f"{self.prompt_version}.txt"

    def api_key(self) -> str | None:
        if self.provider == "gemini":
            return os.getenv("GEMINI_API_KEY")
        if self.provider == "openai":
            return os.getenv("OPENAI_API_KEY")
        return None


def load_fulltext_config(path: str | Path) -> FullTextConfig:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text) or {}
    cfg = FullTextConfig(**raw)
    cfg.source_path = path
    cfg.source_text = text
    return cfg
