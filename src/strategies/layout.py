"""
Strategy B — LayoutExtractor (FR-2.3, FR-2.7).
Uses Docling; adapter normalizes to ExtractedDocument preserving tables (headers+rows),
figures with captions, bounding boxes, and reading order. Error handling for corrupt pages and API failures.
"""

from __future__ import annotations

import time
from pathlib import Path

from src.config import RefineryConfig
from src.models.document_profile import BoundingBox, DocumentProfile
from src.models.extracted_document import (
    ExtractedDocument,
    ExtractionResult,
    Figure,
    ReadingOrderItem,
    Table,
    TextBlock,
)


def _bbox_from_docling_item(item) -> BoundingBox | None:
    """Extract BoundingBox from Docling item (prov or bbox attribute)."""
    if item is None:
        return None
    prov = getattr(item, "prov", None)
    if prov is not None:
        bbox = getattr(prov, "bbox", None)
        if bbox is not None and hasattr(bbox, "l") and hasattr(bbox, "r"):
            return BoundingBox(
                x0=float(bbox.l),
                top=float(getattr(bbox, "t", 0)),
                x1=float(bbox.r),
                bottom=float(getattr(bbox, "b", 0)),
            )
        # tuple/list (l, t, r, b) or (x0, top, x1, bottom)
        if hasattr(bbox, "__len__") and len(bbox) >= 4:
            return BoundingBox(
                x0=float(bbox[0]),
                top=float(bbox[1]),
                x1=float(bbox[2]),
                bottom=float(bbox[3]),
            )
    bbox = getattr(item, "bbox", None)
    if bbox is not None and hasattr(bbox, "__len__") and len(bbox) >= 4:
        return BoundingBox(
            x0=float(bbox[0]),
            top=float(bbox[1]),
            x1=float(bbox[2]),
            bottom=float(bbox[3]),
        )
    return None


def _page_from_docling_item(item) -> int:
    """Extract 1-based page number from Docling item."""
    if item is None:
        return 1
    prov = getattr(item, "prov", None)
    if prov is not None:
        p = getattr(prov, "page_no", None) or getattr(prov, "page_number", None)
        if p is not None:
            return int(p) + 1 if int(p) >= 0 else 1
    return 1


def _table_to_our_schema(tbl, index: int) -> tuple[Table | None, ReadingOrderItem | None]:
    """Convert one Docling table to Table with headers+rows and bbox; return (Table, reading_order item)."""
    try:
        headers: list[str] = []
        rows: list[list[str] | dict] = []
        if hasattr(tbl, "export_to_dataframe"):
            df = tbl.export_to_dataframe()
            headers = list(df.columns.astype(str))
            rows = [list(row) for row in df.itertuples(index=False)]
        elif hasattr(tbl, "export_to_markdown"):
            md_tbl = tbl.export_to_markdown()
            if md_tbl and isinstance(md_tbl, str):
                lines = [ln.strip() for ln in md_tbl.split("\n") if ln.strip()]
                if lines:
                    headers = [lines[0]]
                    rows = [[ln] for ln in lines[1:]] if len(lines) > 1 else []
                else:
                    headers = ["content"]
                    rows = [[md_tbl]]
            else:
                headers = ["content"]
                rows = []
        else:
            headers = []
            rows = []
        caption = getattr(tbl, "caption", None) or getattr(tbl, "title", None)
        if isinstance(caption, str):
            pass
        elif caption is not None and hasattr(caption, "text"):
            caption = str(getattr(caption, "text", ""))
        else:
            caption = None
        return (
            Table(
                headers=headers,
                rows=rows,
                page_number=_page_from_docling_item(tbl),
                bbox=_bbox_from_docling_item(tbl),
                caption=caption,
            ),
            ReadingOrderItem(type="table", index=index),
        )
    except Exception:
        return None, None


def _picture_to_figure(pic, index: int) -> tuple[Figure | None, ReadingOrderItem | None]:
    """Convert one Docling picture to Figure with caption and bbox."""
    try:
        caption = getattr(pic, "caption", None) or getattr(pic, "title", None)
        if isinstance(caption, str):
            pass
        elif caption is not None and hasattr(caption, "text"):
            caption = str(getattr(caption, "text", ""))
        else:
            caption = None
        return (
            Figure(
                caption=caption,
                page_number=_page_from_docling_item(pic),
                bbox=_bbox_from_docling_item(pic),
                image_ref=None,
            ),
            ReadingOrderItem(type="figure", index=index),
        )
    except Exception:
        return None, None


def _docling_to_extracted(
    doc_id: str,
    docling_doc,
) -> tuple[list[TextBlock], list[Table], list[Figure], list[ReadingOrderItem]]:
    """
    Map Docling document to ExtractedDocument schema.
    Preserves text blocks (with bboxes when available), tables as headers+rows with bbox,
    figures with captions and bbox, and reading order (text, table, figure interleaved).
    """
    text_blocks: list[TextBlock] = []
    tables: list[Table] = []
    figures: list[Figure] = []
    reading_order: list[ReadingOrderItem] = []

    # Full-doc markdown fallback for text
    try:
        md = docling_doc.export_to_markdown()
    except Exception:
        md = ""

    # Try structured body first (Docling v2: document body with ordered elements)
    try:
        body = getattr(docling_doc, "body", None)
        if body is not None and hasattr(body, "__iter__"):
            text_idx = 0
            table_idx = 0
            figure_idx = 0
            for elem in body:
                try:
                    tag = getattr(elem, "tag", None) or type(elem).__name__.lower()
                    if "table" in str(tag):
                        tbl, ro = _table_to_our_schema(elem, table_idx)
                        if tbl is not None and ro is not None:
                            tables.append(tbl)
                            reading_order.append(ro)
                            table_idx += 1
                    elif "picture" in str(tag) or "figure" in str(tag) or "image" in str(tag):
                        fig, ro = _picture_to_figure(elem, figure_idx)
                        if fig is not None and ro is not None:
                            figures.append(fig)
                            reading_order.append(ro)
                            figure_idx += 1
                    else:
                        text_content = getattr(elem, "text", None) or ""
                        if hasattr(elem, "export_to_markdown"):
                            text_content = elem.export_to_markdown()
                        if text_content:
                            text_blocks.append(
                                TextBlock(
                                    text=text_content if isinstance(text_content, str) else str(text_content),
                                    page_number=_page_from_docling_item(elem),
                                    bbox=_bbox_from_docling_item(elem),
                                    block_type="paragraph",
                                )
                            )
                            reading_order.append(ReadingOrderItem(type="text", index=text_idx))
                            text_idx += 1
                except Exception:
                    continue
            if reading_order:
                return text_blocks, tables, figures, reading_order
    except Exception:
        pass

    # Fallback: single markdown text block + explicit tables + pictures
    if md:
        text_blocks.append(
            TextBlock(text=md, page_number=1, bbox=None, block_type="paragraph")
        )
        reading_order.append(ReadingOrderItem(type="text", index=0))

    # Tables with headers+rows and bbox
    try:
        doc_tables = getattr(docling_doc, "tables", None) or []
        for i, tbl in enumerate(doc_tables):
            t, ro = _table_to_our_schema(tbl, i)
            if t is not None:
                tables.append(t)
                if ro is not None:
                    reading_order.append(ro)
    except Exception:
        pass

    # Figures/pictures with captions and bbox
    try:
        pics = getattr(docling_doc, "pictures", None) or getattr(docling_doc, "figures", None) or []
        for i, pic in enumerate(pics):
            fig, ro = _picture_to_figure(pic, i)
            if fig is not None:
                figures.append(fig)
                if ro is not None:
                    reading_order.append(ro)
    except Exception:
        pass

    return text_blocks, tables, figures, reading_order


class LayoutExtractor:
    """Strategy B: Docling-based layout-aware extraction; adapter preserves tables, figures, bboxes, reading order."""

    def extract(
        self,
        document_path: Path | str,
        profile: DocumentProfile,
        config: RefineryConfig,
    ) -> ExtractionResult:
        """
        Convert with Docling and normalize to ExtractedDocument.
        Preserves text blocks with bboxes, tables (headers+rows), figures with captions, and reading order.
        Handles corrupt pages, API failures, and empty extraction with low confidence.
        """
        path = Path(document_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {path}")

        start = time.perf_counter()
        try:
            from docling.document_converter import DocumentConverter

            converter = DocumentConverter()
            result = converter.convert(str(path))
            docling_doc = result.document
        except ImportError:
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
                strategy_name="layout",
                cost_estimate=None,
                processing_time_seconds=time.perf_counter() - start,
            )
        except Exception:
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
                strategy_name="layout",
                cost_estimate=None,
                processing_time_seconds=time.perf_counter() - start,
            )

        try:
            text_blocks, tables, figures, reading_order = _docling_to_extracted(
                profile.doc_id, docling_doc
            )
        except Exception:
            text_blocks, tables, figures, reading_order = [], [], [], []

        # Empty extraction: low confidence
        has_content = bool(text_blocks or tables or figures) or any(
            t.text.strip() for t in text_blocks
        )
        confidence = 0.85 if has_content else 0.2

        doc = ExtractedDocument(
            doc_id=profile.doc_id,
            text_blocks=text_blocks,
            tables=tables,
            figures=figures,
            reading_order=reading_order,
        )
        elapsed = time.perf_counter() - start
        return ExtractionResult(
            document=doc,
            confidence_score=confidence,
            strategy_name="layout",
            cost_estimate=None,
            processing_time_seconds=elapsed,
        )
