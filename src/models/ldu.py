"""
LDU (Logical Document Unit) and ChunkRelationship (api_contracts §3.4).
Chunk output of ChunkingEngine with provenance and optional chunk relationships.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from src.models.document_profile import BoundingBox


# -----------------------------------------------------------------------------
# Chunk type and relationships (FR-3.1, FR-3.2)
# -----------------------------------------------------------------------------

ChunkType = Literal["paragraph", "table", "figure", "list", "heading"]


class ChunkRelationship(BaseModel):
    """Cross-reference from one LDU to another (e.g. continues, references)."""

    relationship_type: Literal["continues", "references", "same_section", "parent"] = Field(
        description="Kind of relationship to the target chunk."
    )
    target_content_hash: str = Field(description="content_hash of the related LDU.")


# -----------------------------------------------------------------------------
# LDU (Logical Document Unit) — FR-3.1, FR-3.2, FR-3.4
# -----------------------------------------------------------------------------


class LDU(BaseModel):
    """
    Logical Document Unit: one chunk of document content with spatial and
    provenance metadata. Carries content_hash, page_refs, bounding_box,
    parent_section, and optional chunk relationships.
    """

    content: str = Field(description="Text content of the chunk (FR-3.1).")
    chunk_type: ChunkType = Field(
        description="E.g. paragraph, table, figure, list."
    )
    page_refs: list[int] = Field(
        description="Page numbers (1-based; use consistently per document)."
    )
    bounding_box: BoundingBox | None = Field(
        default=None,
        description="Optional; use when chunk maps to a single bbox.",
    )
    parent_section: str | None = Field(
        default=None,
        description="Section header or title (FR-3.2 rule 4).",
    )
    token_count: int = Field(description="Approximate token count.")
    content_hash: str = Field(
        description="Stable hash for provenance (FR-3.4).",
    )
    metadata: dict | None = Field(
        default=None,
        description="E.g. figure caption, table caption, cross-refs (FR-3.2 rules 2, 5).",
    )
    doc_id: str = Field(description="Source document.")
    relationships: list[ChunkRelationship] | None = Field(
        default=None,
        description="Optional cross-references to other LDUs.",
    )

    @model_validator(mode="after")
    def check_invariants(self) -> "LDU":
        if self.token_count < 0:
            raise ValueError("token_count must be >= 0")
        if not self.page_refs:
            raise ValueError("page_refs must be non-empty")
        return self
