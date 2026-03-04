"""
ProvenanceChain and ProvenanceCitation (api_contracts §3.6, FR-5.2).
Citation chain for query answers and audit mode.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.models.document_profile import BoundingBox


# -----------------------------------------------------------------------------
# ProvenanceCitation — one cited source
# -----------------------------------------------------------------------------


class ProvenanceCitation(BaseModel):
    """Single citation: document, page, optional bbox and content_hash."""

    document_name: str = Field(
        description="Document identifier or file name.",
    )
    page_number: int = Field(description="Page number.")
    bbox: BoundingBox | None = Field(
        default=None,
        description="Optional bounding box.",
    )
    content_hash: str | None = Field(
        default=None,
        description="LDU content_hash when applicable.",
    )
    content_snippet: str | None = Field(
        default=None,
        description="Optional short snippet for display.",
    )


# -----------------------------------------------------------------------------
# ProvenanceChain — ordered list of citations (FR-5.2)
# -----------------------------------------------------------------------------


class ProvenanceChain(BaseModel):
    """Ordered list of citations for a query answer or audit result."""

    citations: list[ProvenanceCitation] = Field(
        default_factory=list,
        description="Ordered list (FR-5.2); by relevance or document order.",
    )
