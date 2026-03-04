"""
ExtractedDocument and nested types (api_contracts §3.2, §3.3).
Normalized output of any extraction strategy; adapters map MinerU/Docling/VLM into this schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.models.document_profile import BoundingBox


# -----------------------------------------------------------------------------
# Nested types (api_contracts §3.2)
# -----------------------------------------------------------------------------


class TextBlock(BaseModel):
    """Single text block with optional bbox and block type."""

    text: str = Field(description="Text content.")
    page_number: int = Field(description="1-based page number.")
    bbox: BoundingBox | None = Field(default=None, description="Bounding box in points.")
    block_type: str | None = Field(default=None, description="E.g. paragraph, heading.")


class Table(BaseModel):
    """Table with headers and rows."""

    headers: list[str] = Field(description="Column headers.")
    rows: list[list[str] | dict] = Field(description="Rows as list of lists or dicts.")
    page_number: int = Field(description="1-based page number.")
    bbox: BoundingBox | None = Field(default=None, description="Bounding box.")
    caption: str | None = Field(default=None, description="Optional table caption.")


class Figure(BaseModel):
    """Figure with optional caption and bbox."""

    caption: str | None = Field(default=None, description="Figure caption.")
    page_number: int = Field(description="1-based page number.")
    bbox: BoundingBox | None = Field(default=None, description="Bounding box.")
    image_ref: str | None = Field(default=None, description="Optional image path or placeholder.")


class ReadingOrderItem(BaseModel):
    """Discriminated reference into text_blocks, tables, or figures (api_contracts §3.2)."""

    type: Literal["text", "table", "figure"] = Field(description="Which list is referenced.")
    index: int = Field(ge=0, description="Index into that list.")


# -----------------------------------------------------------------------------
# ExtractedDocument (FR-2.7)
# -----------------------------------------------------------------------------


class ExtractedDocument(BaseModel):
    """Normalized output of any extraction strategy."""

    doc_id: str = Field(description="Source document id.")
    text_blocks: list[TextBlock] = Field(default_factory=list, description="Ordered text with bbox.")
    tables: list[Table] = Field(default_factory=list, description="Tables as structured data.")
    figures: list[Figure] = Field(default_factory=list, description="Figures with captions.")
    reading_order: list[ReadingOrderItem] = Field(
        default_factory=list,
        description="Ordered references for reading order.",
    )


# -----------------------------------------------------------------------------
# ExtractionResult (api_contracts §3.7)
# -----------------------------------------------------------------------------

StrategyName = Literal["fast_text", "layout", "vision"]


class ExtractionResult(BaseModel):
    """Output of any extractor; used for escalation and ledger."""

    document: ExtractedDocument = Field(description="Normalized extraction.")
    confidence_score: float = Field(ge=0.0, le=1.0, description="Used for escalation.")
    strategy_name: StrategyName = Field(description="Which strategy produced this.")
    cost_estimate: float | None = Field(default=None, description="For Vision; optional for others.")
    processing_time_seconds: float | None = Field(default=None, description="Optional.")


# -----------------------------------------------------------------------------
# Ledger entry (api_contracts §5, FR-2.8, DR-3)
# -----------------------------------------------------------------------------


class LedgerEntry(BaseModel):
    """One line in .refinery/extraction_ledger.jsonl (append-only)."""

    doc_id: str = Field(description="Document.")
    strategy_used: str = Field(description='"fast_text" | "layout" | "vision".')
    confidence_score: float = Field(ge=0.0, le=1.0, description="In [0, 1].")
    cost_estimate: float = Field(description="Numeric (tokens or USD); 0 if not applicable.")
    processing_time: float = Field(description="Seconds.")
    timestamp_utc: str | None = Field(default=None, description="ISO 8601.")
    escalated_from: str | None = Field(default=None, description="Previous strategy if escalation.")
