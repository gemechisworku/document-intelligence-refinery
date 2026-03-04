"""
Strategy A — FastTextExtractor (FR-2.1, FR-2.2).
Uses pdfplumber; confidence combines character count, character density, image area ratio,
and font metadata. Thresholds from config (extraction.*). Low confidence triggers escalation.
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
    char_density: float,
    image_ratio_avg: float,
    font_metadata_ratio: float,
    min_chars: int,
    max_image_ratio: float,
) -> float:
    """
    Compute confidence in [0, 1] from multiple signals (FR-2.2).
    Thresholds: min_chars (config), max_image_ratio (config).
    Signals: character count per page, character density (chars per 1000 pt²),
    image-to-page area ratio, font metadata (fraction of chars with font info).
    """
    # Character count score (vs min_chars)
    char_score = (
        min(1.0, chars_per_page_avg / max(min_chars * 5, 1))
        if chars_per_page_avg >= min_chars
        else max(0.0, chars_per_page_avg / max(min_chars, 1))
    )
    # Density: higher density typically indicates native text (arbitrary scale: 0.1 chars/pt² ≈ 500 chars on 5000 pt² page)
    density_scale = 0.05  # chars per pt² for "good" density
    density_score = min(1.0, char_density / density_scale) if char_density else 0.0
    # Image ratio score
    if image_ratio_avg <= max_image_ratio:
        image_score = 1.0 - (image_ratio_avg / max_image_ratio) if max_image_ratio else 1.0
    else:
        image_score = max(0.0, 1.0 - (image_ratio_avg - max_image_ratio) / (1.0 - max_image_ratio))
    # Font metadata: digital PDFs usually have font info; scanned/OCR may have less
    font_score = min(1.0, font_metadata_ratio * 1.2)  # slight boost if most chars have font
    # Equal-weight combination of the four signals
    combined = (char_score + density_score + image_score + font_score) / 4.0
    return max(0.0, min(1.0, combined))


def _bbox_from_dict(d: dict, page_width: float, page_height: float) -> BoundingBox | None:
    """Build BoundingBox from pdfplumber char/word dict (x0, top, x1, bottom) or None."""
    x0 = d.get("x0")
    top = d.get("top")
    x1 = d.get("x1")
    bottom = d.get("bottom")
    if x0 is None or top is None or x1 is None or bottom is None:
        return None
    return BoundingBox(x0=float(x0), top=float(top), x1=float(x1), bottom=float(bottom))


class FastTextExtractor:
    """Strategy A: pdfplumber-based extraction; multi-signal confidence for escalation."""

    def extract(
        self,
        document_path: Path | str,
        profile: DocumentProfile,
        config: RefineryConfig,
    ) -> ExtractionResult:
        """
        Extract text via pdfplumber; one TextBlock per page with spatial provenance.
        Confidence combines: character count, character density, image-to-page ratio,
        and font metadata (thresholds from config.extraction).
        Corrupt or unreadable pages are skipped; empty extraction yields low confidence.
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
        chars_with_font = 0
        pages_analyzed = 0

        try:
            with pdfplumber.open(path) as pdf:
                for i, page in enumerate(pdf.pages):
                    try:
                        w = page.width
                        h = page.height
                        page_area = w * h
                        total_page_area += page_area
                        text = page.extract_text() or ""
                        char_count = len(text.replace("\n", " ").strip())
                        if not char_count and page.chars:
                            char_count = len(page.chars)
                        total_chars += char_count
                        # Font metadata: count chars that have fontname (digital signal)
                        for c in page.chars or []:
                            if isinstance(c, dict) and c.get("fontname"):
                                chars_with_font += 1
                            elif getattr(c, "fontname", None):
                                chars_with_font += 1
                        if not page.chars and char_count:
                            chars_with_font += char_count  # assume text from extract_text has font context
                        img_area = 0.0
                        for im in page.images or []:
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
                    except Exception:
                        # Corrupt or unreadable page: skip, add empty block to keep page numbering
                        try:
                            w = getattr(page, "width", 612)
                            h = getattr(page, "height", 792)
                        except Exception:
                            w, h = 612, 792
                        text_blocks.append(
                            TextBlock(
                                text="",
                                page_number=i + 1,
                                bbox=BoundingBox(x0=0, top=0, x1=w, bottom=h),
                                block_type="paragraph",
                            )
                        )
        except Exception:
            # API/file failure: return empty document with zero confidence
            elapsed = time.perf_counter() - start
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
                strategy_name="fast_text",
                cost_estimate=None,
                processing_time_seconds=elapsed,
            )

        chars_per_page = total_chars / pages_analyzed if pages_analyzed else 0.0
        image_ratio = (
            total_image_area / total_page_area if total_page_area else 0.0
        )
        char_density = (total_chars / total_page_area) if total_page_area else 0.0
        font_metadata_ratio = (chars_with_font / total_chars) if total_chars else 0.0

        confidence = _confidence_from_metrics(
            chars_per_page,
            char_density,
            image_ratio,
            font_metadata_ratio,
            min_chars,
            max_image,
        )

        # Empty extraction: low confidence
        if not text_blocks or not any(tb.text.strip() for tb in text_blocks):
            confidence = min(confidence, 0.3)

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
