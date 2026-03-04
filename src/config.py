"""
Configuration loading (api_contracts §4).
RefineryConfig holds paths and extraction/chunking rules; load from YAML + env.
All triage thresholds and domain keyword lists are externalized (IR-2, NFR-3).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Triage configuration (FR-1.x) — all thresholds and domain keywords in config
# -----------------------------------------------------------------------------


class TriageConfig(BaseModel):
    """
    Triage Agent thresholds and domain keyword lists (FR-1.1–FR-1.7).
    Add or edit keywords in YAML to change domain classification without code changes.
    """

    # Origin type (scanned vs native vs mixed vs form_fillable)
    scanned_chars_per_page_max: int = Field(
        default=100,
        description="Below this chars/page with high image ratio → scanned_image.",
    )
    scanned_image_ratio_min: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Above this image ratio with low chars → scanned_image.",
    )
    native_chars_per_page_min: int = Field(
        default=500,
        description="Above this with low image ratio → native_digital.",
    )
    native_image_ratio_max: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Below this image ratio with high chars → native_digital.",
    )
    # Layout complexity
    figure_heavy_image_ratio_min: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Above this → figure_heavy.",
    )
    mixed_image_ratio_min: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Above this (below figure_heavy) → mixed.",
    )
    table_heavy_chars_per_page_min: int = Field(
        default=1500,
        description="Above this with low image ratio → table_heavy.",
    )
    table_heavy_image_ratio_max: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Below this with high chars → table_heavy.",
    )
    # Domain hint: keywords per domain (filename/content hints). Order of keys
    # can define priority; first match wins. "general" is fallback (no keywords needed).
    domain_keywords: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "financial": [
                "annual report",
                "financial",
                "audit",
                "revenue",
                "expenditure",
                "tax",
                "statement",
            ],
            "legal": ["audit", "legal", "regulation", "compliance"],
            "technical": ["survey", "assessment", "fta", "performance", "technical"],
            "medical": ["medical", "health", "clinical"],
            "general": [],
        },
        description="Keywords (substrings) per domain for filename-based classification.",
    )


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
    triage: TriageConfig = Field(default_factory=TriageConfig)
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
            if "triage" in raw:
                defaults.setdefault("triage", {}).update(raw["triage"])
            if "extraction" in raw:
                defaults.setdefault("extraction", {}).update(raw["extraction"])
        except Exception:
            pass
    if overrides:
        defaults.update(overrides)
    return RefineryConfig(**defaults)
