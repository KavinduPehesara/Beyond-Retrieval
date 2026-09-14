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
            "Cap per review. Keep this small while developing — it is the "
            "cheapest guard against an accidental full-corpus run. Set to "
            "null only for runs you intend to report."
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


class ScreeningConfig(BaseModel):
    """How the language model is called."""

    provider: Literal["gemini", "mock"] = "mock"
    model: str = "gemini-2.0-flash"
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
    usd_per_1m_input: float = 0.15
    usd_per_1m_output: float = 0.60


class Config(BaseModel):
    name: str
    dataset: DatasetConfig
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
