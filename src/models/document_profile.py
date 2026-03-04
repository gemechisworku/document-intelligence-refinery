"""
DocumentProfile and BoundingBox models (api_contracts §3.1, §3.2).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


# -----------------------------------------------------------------------------
# BoundingBox (DR-2) — single representation for all bbox coordinates
# -----------------------------------------------------------------------------


class BoundingBox(BaseModel):
    """Bounding box in pdfplumber-style coordinates (points; origin top-left)."""

    x0: float = Field(description="Left.")
    top: float = Field(description="Top.")
    x1: float = Field(description="Right.")
    bottom: float = Field(description="Bottom.")

    @model_validator(mode="after")
    def check_bounds(self) -> "BoundingBox":
        if self.x0 > self.x1 or self.top > self.bottom:
            msg = "Invariant: x0 <= x1 and top <= bottom"
            raise ValueError(msg)
        return self


# -----------------------------------------------------------------------------
# DocumentProfile (FR-1.x) — Triage Agent output
# -----------------------------------------------------------------------------

OriginType = Literal["native_digital", "scanned_image", "mixed", "form_fillable"]
LayoutComplexity = Literal[
    "single_column", "multi_column", "table_heavy", "figure_heavy", "mixed"
]
DomainHint = Literal["financial", "legal", "technical", "medical", "general"]
EstimatedExtractionCost = Literal[
    "fast_text_sufficient", "needs_layout_model", "needs_vision_model"
]


class DocumentProfile(BaseModel):
    """Classification output of the Triage Agent (FR-1.1–FR-1.5)."""

    doc_id: str = Field(description="Document identifier.")
    origin_type: OriginType = Field(description="Native digital, scanned, mixed, or form.")
    layout_complexity: LayoutComplexity = Field(
        description="Single/multi column, table/figure heavy, or mixed."
    )
    language: str = Field(description="Language code (e.g. ISO 639-1).")
    language_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Language detection confidence in [0, 1].",
    )
    domain_hint: DomainHint = Field(
        description="Domain for extraction prompt strategy selection."
    )
    estimated_extraction_cost: EstimatedExtractionCost = Field(
        description="Which extraction strategy tier is expected."
    )
