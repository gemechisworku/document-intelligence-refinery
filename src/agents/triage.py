"""
Triage Agent (FR-1.x, api_contracts §2.1).
Classifies document (origin type, layout complexity, domain hint, etc.) and persists DocumentProfile.
Domain classification is pluggable via DomainClassifier protocol (FR-1.4); all thresholds from config.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import pdfplumber

from src.config import RefineryConfig, TriageConfig, load_config
from src.models.document_profile import (
    DocumentProfile,
    DomainHint,
    EstimatedExtractionCost,
    LayoutComplexity,
    OriginType,
)

# Default analysis sample size (first N pages)
DEFAULT_MAX_PAGES = 20


# -----------------------------------------------------------------------------
# Domain classifier protocol (FR-1.4 — pluggable, e.g. keyword vs VLM)
# -----------------------------------------------------------------------------


@runtime_checkable
class DomainClassifier(Protocol):
    """Protocol for domain hint classification. Swap keyword-based for VLM without changing pipeline."""

    def classify(self, document_path: Path, config: TriageConfig) -> DomainHint:
        """Return domain hint for the document (filename/content/config-driven)."""
        ...


class KeywordDomainClassifier:
    """
    Domain classifier using config-driven keyword lists (no code change to add keywords).
    First matching domain in config order wins; 'general' is fallback.
    """

    def classify(self, document_path: Path, config: TriageConfig) -> DomainHint:
        name_lower = document_path.name.lower()
        # Iterate in deterministic order: financial, legal, technical, medical, general
        for domain in ("financial", "legal", "technical", "medical", "general"):
            keywords = config.domain_keywords.get(domain) or []
            if any(kw in name_lower for kw in keywords):
                return domain  # type: ignore[return-value]
        return "general"


# -----------------------------------------------------------------------------
# PDF analysis and origin/layout classification (all thresholds from config)
# -----------------------------------------------------------------------------


def _analyze_pdf(path: Path, max_pages: int = DEFAULT_MAX_PAGES) -> dict:
    """Compute has_text_stream, chars_per_page_avg, image_area_ratio_avg, pages_analyzed from pdfplumber."""
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
        "total_chars": total_chars,
    }


def _pdf_has_acroform(path: Path) -> bool:
    """Detect if PDF has AcroForm (form-fillable). Uses pdfminer when available."""
    try:
        from pdfminer.pdfparser import PDFParser
        from pdfminer.pdfdocument import PDFDocument
        from pdfminer.pdftypes import resolve1

        with path.open("rb") as fp:
            parser = PDFParser(fp)
            doc = PDFDocument(parser)
            catalog = resolve1(doc.catalog) if doc.catalog else {}
            return catalog.get("/AcroForm") is not None
    except Exception:
        return False


def _classify_origin_type(
    has_text_stream: bool,
    chars_per_page_avg: float,
    image_ratio_avg: float,
    pages_analyzed: int,
    total_chars: int,
    form_fillable: bool,
    cfg: TriageConfig,
) -> OriginType:
    """
    Classify origin type from signals (FR-1.7). All thresholds from config.
    Explicit handling: zero-text -> scanned_image; mixed-mode -> mixed; form fields -> form_fillable.
    """
    # Zero-text: no pages or no extractable text at all
    if pages_analyzed == 0 or (pages_analyzed > 0 and total_chars == 0 and not has_text_stream):
        return "scanned_image"
    # Form-fillable: PDF has AcroForm and some content
    if form_fillable and has_text_stream:
        return "form_fillable"
    if not has_text_stream:
        return "scanned_image"
    if (
        chars_per_page_avg < cfg.scanned_chars_per_page_max
        and image_ratio_avg > cfg.scanned_image_ratio_min
    ):
        return "scanned_image"
    if (
        chars_per_page_avg > cfg.native_chars_per_page_min
        and image_ratio_avg < cfg.native_image_ratio_max
    ):
        return "native_digital"
    return "mixed"


def _classify_layout_complexity(
    chars_per_page_avg: float,
    image_ratio_avg: float,
    cfg: TriageConfig,
) -> LayoutComplexity:
    """Heuristic layout complexity (FR-1.2); all thresholds from config."""
    if image_ratio_avg >= cfg.figure_heavy_image_ratio_min:
        return "figure_heavy"
    if image_ratio_avg >= cfg.mixed_image_ratio_min:
        return "mixed"
    if (
        chars_per_page_avg >= cfg.table_heavy_chars_per_page_min
        and image_ratio_avg <= cfg.table_heavy_image_ratio_max
    ):
        return "table_heavy"
    return "single_column"


def _estimate_extraction_cost(
    origin_type: OriginType, layout_complexity: LayoutComplexity
) -> EstimatedExtractionCost:
    """Set estimated extraction cost from origin and layout (FR-1.5)."""
    if origin_type == "scanned_image":
        return "needs_vision_model"
    if origin_type == "form_fillable":
        return "needs_layout_model"
    if origin_type == "native_digital" and layout_complexity == "single_column":
        return "fast_text_sufficient"
    if layout_complexity in ("multi_column", "table_heavy", "figure_heavy", "mixed"):
        return "needs_layout_model"
    return "needs_layout_model"


# -----------------------------------------------------------------------------
# Triage Agent
# -----------------------------------------------------------------------------


class TriageAgent:
    """
    Classifies each document before extraction (FR-1.x).
    Persists DocumentProfile to .refinery/profiles/{doc_id}.json.
    All thresholds and domain keywords come from config; domain classifier is pluggable.
    """

    def __init__(
        self,
        config: RefineryConfig | None = None,
        domain_classifier: DomainClassifier | None = None,
    ) -> None:
        self._config = config if config is not None else load_config()
        self._domain_classifier = domain_classifier or KeywordDomainClassifier()

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
        """
        path = Path(document_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {path}")

        data = _analyze_pdf(path)
        has_text = data["has_text_stream"]
        chars_avg = data["chars_per_page_avg"]
        image_ratio = data["image_area_ratio_avg"]
        pages_analyzed = data["pages_analyzed"]
        total_chars = data["total_chars"]

        cfg = self._config.triage
        form_fillable = _pdf_has_acroform(path)

        origin_type = _classify_origin_type(
            has_text,
            chars_avg,
            image_ratio,
            pages_analyzed,
            total_chars,
            form_fillable,
            cfg,
        )
        layout_complexity = _classify_layout_complexity(chars_avg, image_ratio, cfg)
        domain_hint = self._domain_classifier.classify(path, cfg)
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
