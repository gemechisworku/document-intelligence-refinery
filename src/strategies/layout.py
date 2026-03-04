"""
Strategy B — LayoutExtractor (FR-2.3, FR-2.7).
Uses Docling; adapter normalizes output to ExtractedDocument.
"""

from __future__ import annotations

import time
from pathlib import Path

from src.config import RefineryConfig
from src.models.document_profile import DocumentProfile
from src.models.extracted_document import (
    ExtractedDocument,
    ExtractionResult,
    Figure,
    ReadingOrderItem,
    Table,
    TextBlock,
)


def _docling_to_extracted(
    doc_id: str,
    docling_doc,
) -> tuple[list[TextBlock], list[Table], list[Figure], list[ReadingOrderItem]]:
    """Map Docling document to our schema; fallback to markdown if structure unavailable."""
    text_blocks: list[TextBlock] = []
    tables: list[Table] = []
    figures: list[Figure] = []
    reading_order: list[ReadingOrderItem] = []

    try:
        md = docling_doc.export_to_markdown()
    except Exception:
        md = ""

    # Single text block from full markdown (layout preserves structure in markdown)
    if md:
        text_blocks.append(
            TextBlock(text=md, page_number=1, bbox=None, block_type="paragraph")
        )
        reading_order.append(ReadingOrderItem(type="text", index=0))

    # Try to extract tables from Docling document if API exposes them
    try:
        if hasattr(docling_doc, "tables") and docling_doc.tables:
            for i, tbl in enumerate(docling_doc.tables):
                try:
                    if hasattr(tbl, "export_to_dataframe"):
                        df = tbl.export_to_dataframe()
                        headers = list(df.columns.astype(str))
                        rows = [list(row) for row in df.itertuples(index=False)]
                    elif hasattr(tbl, "export_to_markdown"):
                        md_tbl = tbl.export_to_markdown()
                        # Minimal parse: treat as one row of text for now
                        headers = ["content"]
                        rows = [[md_tbl]]
                    else:
                        headers = []
                        rows = []
                    tables.append(
                        Table(
                            headers=headers,
                            rows=rows,
                            page_number=1,
                            bbox=None,
                            caption=None,
                        )
                    )
                    reading_order.append(ReadingOrderItem(type="table", index=i))
                except Exception:
                    continue
    except Exception:
        pass

    return text_blocks, tables, figures, reading_order


class LayoutExtractor:
    """Strategy B: Docling-based layout-aware extraction."""

    def extract(
        self,
        document_path: Path | str,
        profile: DocumentProfile,
        config: RefineryConfig,
    ) -> ExtractionResult:
        """
        Convert with Docling and normalize to ExtractedDocument.
        Confidence fixed high (0.85) when conversion succeeds; layout model ran.
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
            # Docling not installed: return empty document with low confidence
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

        text_blocks, tables, figures, reading_order = _docling_to_extracted(
            profile.doc_id, docling_doc
        )
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
            confidence_score=0.85,
            strategy_name="layout",
            cost_estimate=None,
            processing_time_seconds=elapsed,
        )
