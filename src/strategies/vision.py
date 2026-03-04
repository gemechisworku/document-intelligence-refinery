"""
Strategy C — VisionExtractor (FR-2.4, FR-2.9).
VLM via OpenRouter; budget_guard; adapter to ExtractedDocument.
Stub: when no API key or for tests, returns low-confidence result; otherwise can call OpenRouter.
"""

from __future__ import annotations

import time
from pathlib import Path

from src.config import RefineryConfig
from src.exceptions import ExtractionBudgetExceeded
from src.models.document_profile import DocumentProfile
from src.models.extracted_document import (
    ExtractedDocument,
    ExtractionResult,
)


class VisionExtractor:
    """Strategy C: VLM-based extraction with per-document budget cap (FR-2.9, BR-3)."""

    def extract(
        self,
        document_path: Path | str,
        profile: DocumentProfile,
        config: RefineryConfig,
    ) -> ExtractionResult:
        """
        Stub: if no OpenRouter API key, return empty document with 0.0 confidence.
        When implemented: call OpenRouter with page images, enforce vision_budget_cap_per_doc,
        raise ExtractionBudgetExceeded when cap exceeded.
        """
        path = Path(document_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {path}")

        start = time.perf_counter()
        if not config.openrouter_api_key:
            doc = ExtractedDocument(
                doc_id=profile.doc_id,
                text_blocks=[],
                tables=[],
                figures=[],
                reading_order=[],
            )
            return ExtractionResult(
                document=doc,
                confidence_score=0.0,
                strategy_name="vision",
                cost_estimate=0.0,
                processing_time_seconds=time.perf_counter() - start,
            )

        # Placeholder: real implementation would render PDF pages to images,
        # call OpenRouter vision API, track cost vs config.vision_budget_cap_per_doc,
        # raise ExtractionBudgetExceeded if exceeded, and map response to ExtractedDocument.
        cost_so_far = 0.0
        if cost_so_far > config.vision_budget_cap_per_doc:
            raise ExtractionBudgetExceeded(
                f"Vision budget cap ({config.vision_budget_cap_per_doc}) exceeded."
            )

        doc = ExtractedDocument(
            doc_id=profile.doc_id,
            text_blocks=[],
            tables=[],
            figures=[],
            reading_order=[],
        )
        return ExtractionResult(
            document=doc,
            confidence_score=0.0,
            strategy_name="vision",
            cost_estimate=0.0,
            processing_time_seconds=time.perf_counter() - start,
        )
