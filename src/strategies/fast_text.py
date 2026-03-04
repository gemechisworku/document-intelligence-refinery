"""
Strategy A — FastTextExtractor (FR-2.1, FR-2.2).
Uses pdfplumber; confidence from character count, image area ratio; low confidence triggers escalation.
"""

from __future__ import annotations

import time
from pathlib import Path

import pdfplumber

from src.config import RefineryConfig
from src.models.document_profile import BoundingBox, DocumentProfile
from src.models.extracted_document import (
    ExtractedDocument,
    ExtractionResult,
    ReadingOrderItem,
    TextBlock,
)


def _confidence_from_metrics(
    chars_per_page_avg: float,
    image_ratio_avg: float,
    min_chars: int,
    max_image_ratio: float,
) -> float:
    """Compute confidence in [0, 1] for fast text extraction (FR-2.2)."""
    if chars_per_page_avg >= min_chars and image_ratio_avg <= max_image_ratio:
        # Good regime: high chars, low image share
        char_score = min(1.0, chars_per_page_avg / max(min_chars * 5, 1))
        image_score = 1.0 - (image_ratio_avg / max_image_ratio) if max_image_ratio else 1.0
        return min(1.0, (char_score + image_score) / 2)
    if chars_per_page_avg < min_chars:
        char_score = max(0.0, chars_per_page_avg / max(min_chars, 1))
    else:
        char_score = 1.0
    if image_ratio_avg > max_image_ratio:
        image_score = max(0.0, 1.0 - (image_ratio_avg - max_image_ratio) / (1.0 - max_image_ratio))
    else:
        image_score = 1.0
    return max(0.0, min(1.0, (char_score + image_score) / 2))


class FastTextExtractor:
    """Strategy A: pdfplumber-based extraction; confidence gate for escalation."""

    def extract(
        self,
        document_path: Path | str,
        profile: DocumentProfile,
        config: RefineryConfig,
    ) -> ExtractionResult:
        """
        Extract text via pdfplumber; one TextBlock per page; no tables/figures.
        Confidence from chars/page and image area ratio vs config thresholds.
        """
        path = Path(document_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {path}")

        start = time.perf_counter()
        ec = config.extraction
        min_chars = ec.fast_text_min_char_count_per_page
        max_image = ec.fast_text_max_image_area_ratio

        text_blocks: list[TextBlock] = []
        total_chars = 0
        total_page_area = 0.0
        total_image_area = 0.0
        pages_analyzed = 0

        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                w, h = page.width, page.height
                page_area = w * h
                total_page_area += page_area
                text = page.extract_text() or ""
                char_count = len(text.replace("\n", " ").strip())
                if not char_count and page.chars:
                    char_count = len(page.chars)
                total_chars += char_count
                img_area = 0.0
                for im in page.images:
                    x0 = im.get("x0", 0)
                    top = im.get("top", 0)
                    x1 = im.get("x1", 0)
                    bottom = im.get("bottom", 0)
                    img_area += (x1 - x0) * (bottom - top)
                total_image_area += img_area
                pages_analyzed += 1
                bbox = BoundingBox(x0=0, top=0, x1=w, bottom=h) if page_area else None
                text_blocks.append(
                    TextBlock(
                        text=text or "",
                        page_number=i + 1,
                        bbox=bbox,
                        block_type="paragraph",
                    )
                )

        chars_per_page = total_chars / pages_analyzed if pages_analyzed else 0.0
        image_ratio = (
            total_image_area / total_page_area if total_page_area else 0.0
        )
        confidence = _confidence_from_metrics(
            chars_per_page, image_ratio, min_chars, max_image
        )

        reading_order = [
            ReadingOrderItem(type="text", index=j) for j in range(len(text_blocks))
        ]
        doc = ExtractedDocument(
            doc_id=profile.doc_id,
            text_blocks=text_blocks,
            tables=[],
            figures=[],
            reading_order=reading_order,
        )
        elapsed = time.perf_counter() - start
        return ExtractionResult(
            document=doc,
            confidence_score=confidence,
            strategy_name="fast_text",
            cost_estimate=None,
            processing_time_seconds=elapsed,
        )
