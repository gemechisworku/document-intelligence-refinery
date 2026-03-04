"""
Extractor protocol (api_contracts §2.3).
All strategies implement extract(document_path, profile, config) -> ExtractionResult.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from src.models.document_profile import DocumentProfile
from src.models.extracted_document import ExtractionResult

if TYPE_CHECKING:
    from src.config import RefineryConfig


class ExtractorProtocol(Protocol):
    """Interface for extraction strategies."""

    def extract(
        self,
        document_path: Path | str,
        profile: DocumentProfile,
        config: RefineryConfig,
    ) -> ExtractionResult:
        """Extract document content; return normalized result and confidence."""
        ...