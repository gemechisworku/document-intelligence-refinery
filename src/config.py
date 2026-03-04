"""
Configuration loading (api_contracts §4).
RefineryConfig holds paths and extraction/chunking rules; load from YAML + env.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ExtractionConfig(BaseModel):
    """Extraction thresholds (rubric/extraction_rules.yaml)."""

    fast_text_min_char_count_per_page: int = Field(
        default=100,
        description="Below this, page is likely image-only or scanned; escalate.",
    )
    fast_text_max_image_area_ratio: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Above this, fast text will miss most content.",
    )
    confidence_escalation_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="If Strategy A/B confidence below this, escalate.",
    )


class ChunkingConfig(BaseModel):
    """Chunking rules (api_contracts §4.3); used in Phase 3."""

    max_tokens_per_ldu: int = Field(default=512, description="Max tokens per LDU.")


class RefineryConfig(BaseModel):
    """Root config (api_contracts §4.1)."""

    refinery_dir: Path | str = Field(
        default=Path(".refinery"),
        description="Base path for profiles, pageindex, ledger.",
    )
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    vision_budget_cap_per_doc: float = Field(
        default=10.0,
        ge=0.0,
        description="Max token cost (or USD) per document for Strategy C (FR-2.9).",
    )
    openrouter_api_key: str | None = Field(default=None, description="From env; required when Strategy C is used.")
    openrouter_model: str | None = Field(
        default="google/gemini-flash-1.5",
        description="E.g. google/gemini-flash-1.5, openai/gpt-4o-mini.",
    )

    def get_profiles_dir(self) -> Path:
        """Return path to .refinery/profiles/."""
        base = Path(self.refinery_dir)
        return base / "profiles"

    def get_profile_path(self, doc_id: str) -> Path:
        """Return path to .refinery/profiles/{doc_id}.json."""
        return self.get_profiles_dir() / f"{doc_id}.json"

    def get_ledger_path(self) -> Path:
        """Return path to .refinery/extraction_ledger.jsonl."""
        return Path(self.refinery_dir) / "extraction_ledger.jsonl"


def load_config(
    refinery_dir: Path | str | None = None,
    overrides: dict[str, Any] | None = None,
    project_root: Path | None = None,
) -> RefineryConfig:
    """Load RefineryConfig from defaults; optionally from rubric/extraction_rules.yaml."""
    defaults: dict[str, Any] = {}
    if refinery_dir is not None:
        defaults["refinery_dir"] = Path(refinery_dir)
    root = project_root or Path.cwd()
    yaml_path = root / "rubric" / "extraction_rules.yaml"
    if yaml_path.exists():
        try:
            import yaml
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            if "extraction" in raw:
                defaults.setdefault("extraction", {}).update(raw["extraction"])
        except Exception:
            pass
    if overrides:
        defaults.update(overrides)
    return RefineryConfig(**defaults)
