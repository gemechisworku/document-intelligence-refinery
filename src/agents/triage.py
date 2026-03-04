"""
Triage Agent (FR-1.x, api_contracts §2.1).
Classifies document (origin type, layout complexity, domain hint, etc.) and persists DocumentProfile.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber

from src.config import RefineryConfig, load_config
from src.models.document_profile import (
    DocumentProfile,
    DomainHint,
    EstimatedExtractionCost,
    LayoutComplexity,
    OriginType,
)

# Default analysis sample size (first N pages)
DEFAULT_MAX_PAGES = 20


def _analyze_pdf(path: Path, max_pages: int = DEFAULT_MAX_PAGES) -> dict:
    """Compute has_text_stream, chars_per_page_avg, image_area_ratio_avg from pdfplumber."""
    total_chars = 0
    total_page_area = 0.0
    total_image_area = 0.0
    has_text_stream = False
    pages_analyzed = 0
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            if i >= max_pages:
                break
            w, h = page.width, page.height
            page_area = w * h
            total_page_area += page_area
            text = page.extract_text() or ""
            char_count = len(text.replace(" ", "").replace("\n", ""))
            raw_char_count = len(page.chars)
            if raw_char_count > 0:
                has_text_stream = True
            char_count = max(char_count, raw_char_count)
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
    chars_per_page_avg = total_chars / pages_analyzed if pages_analyzed else 0.0
    image_ratio_avg = (
        total_image_area / total_page_area if total_page_area else 0.0
    )
    return {
        "has_text_stream": has_text_stream,
        "chars_per_page_avg": chars_per_page_avg,
        "image_area_ratio_avg": image_ratio_avg,
        "pages_analyzed": pages_analyzed,
    }


def _classify_origin_type(
    has_text_stream: bool,
    chars_per_page_avg: float,
    image_ratio_avg: float,
    *,
    scanned_chars_max: float = 100,
    scanned_image_min: float = 0.3,
    native_chars_min: float = 500,
    native_image_max: float = 0.5,
) -> OriginType:
    """Classify origin type from corpus-derived heuristics (FR-1.7)."""
    if not has_text_stream:
        return "scanned_image"
    if chars_per_page_avg < scanned_chars_max and image_ratio_avg > scanned_image_min:
        return "scanned_image"
    if (
        has_text_stream
        and chars_per_page_avg > native_chars_min
        and image_ratio_avg < native_image_max
    ):
        return "native_digital"
    return "mixed"


def _classify_layout_complexity(
    chars_per_page_avg: float,
    image_ratio_avg: float,
    *,
    figure_heavy_image_min: float = 0.4,
    mixed_image_min: float = 0.2,
    table_heavy_chars_min: float = 1500,
    table_heavy_image_max: float = 0.1,
) -> LayoutComplexity:
    """Heuristic layout complexity without a layout model (FR-1.2)."""
    if image_ratio_avg >= figure_heavy_image_min:
        return "figure_heavy"
    if image_ratio_avg >= mixed_image_min:
        return "mixed"
    if (
        chars_per_page_avg >= table_heavy_chars_min
        and image_ratio_avg <= table_heavy_image_max
    ):
        return "table_heavy"
    return "single_column"


def _classify_domain_hint(path: Path) -> DomainHint:
    """Keyword-based domain hint (FR-1.4); pluggable for VLM later."""
    name_lower = path.name.lower()
    if any(
        x in name_lower
        for x in ("annual report", "financial", "audit", "revenue", "expenditure", "tax")
    ):
        return "financial"
    if any(x in name_lower for x in ("audit", "legal", "regulation")):
        return "legal"
    if any(x in name_lower for x in ("survey", "assessment", "fta", "performance")):
        return "technical"
    if any(x in name_lower for x in ("medical", "health")):
        return "medical"
    return "general"


def _estimate_extraction_cost(
    origin_type: OriginType, layout_complexity: LayoutComplexity
) -> EstimatedExtractionCost:
    """Set estimated extraction cost from origin and layout (FR-1.5)."""
    if origin_type == "scanned_image":
        return "needs_vision_model"
    if origin_type == "native_digital" and layout_complexity == "single_column":
        return "fast_text_sufficient"
    if layout_complexity in ("multi_column", "table_heavy", "figure_heavy", "mixed"):
        return "needs_layout_model"
    return "needs_layout_model"


class TriageAgent:
    """
    Classifies each document before extraction (FR-1.x).
    Persists DocumentProfile to .refinery/profiles/{doc_id}.json.
    """

    def __init__(self, config: RefineryConfig | None = None) -> None:
        self._config = config if config is not None else load_config()

    def run(self, document_path: Path | str, doc_id: str) -> DocumentProfile:
        """
        Classify the document and persist DocumentProfile.

        Args:
            document_path: Local or mounted file path to the document.
            doc_id: Unique identifier (used for artifact paths).

        Returns:
            DocumentProfile with all classification dimensions.

        Raises:
            FileNotFoundError: If document_path does not exist.
            ValidationError: On schema validation failure.
        """
        path = Path(document_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {path}")

        data = _analyze_pdf(path)
        has_text = data["has_text_stream"]
        chars_avg = data["chars_per_page_avg"]
        image_ratio = data["image_area_ratio_avg"]

        origin_type = _classify_origin_type(has_text, chars_avg, image_ratio)
        layout_complexity = _classify_layout_complexity(chars_avg, image_ratio)
        domain_hint = _classify_domain_hint(path)
        estimated_cost = _estimate_extraction_cost(origin_type, layout_complexity)

        profile = DocumentProfile(
            doc_id=doc_id,
            origin_type=origin_type,
            layout_complexity=layout_complexity,
            language="en",
            language_confidence=0.9,
            domain_hint=domain_hint,
            estimated_extraction_cost=estimated_cost,
        )

        out_path = self._config.get_profile_path(doc_id)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")

        return profile
