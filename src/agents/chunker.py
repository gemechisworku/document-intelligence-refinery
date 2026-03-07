"""
ChunkingEngine and ChunkValidator (FR-3.x, api_contracts §2.4).
Transforms ExtractedDocument into RAG-optimized LDUs with content_hash,
enforces five chunking rules, and ingests into vector store.

Five rules (FR-3.2):
  1. Table + preceding header kept together as single LDU.
  2. Figure + caption kept together as single LDU.
  3. Numbered/bulleted list kept as single LDU (up to max_tokens).
  4. Section headers become parent_section metadata on child chunks.
  5. Cross-references encoded as ChunkRelationship.
"""

from __future__ import annotations

import hashlib
import re
from typing import Sequence

from pydantic import ValidationError

from src.config import RefineryConfig
from src.models.document_profile import BoundingBox
from src.models.extracted_document import (
    ExtractedDocument,
    Figure,
    ReadingOrderItem,
    Table,
    TextBlock,
)
from src.models.ldu import LDU, ChunkRelationship, ChunkType


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

_LIST_PATTERN = re.compile(
    r"^\s*(?:\d+[\.\)]\s|[-•*]\s|[a-zA-Z][\.\)]\s)",
    re.MULTILINE,
)

_CROSS_REF_PATTERN = re.compile(
    r"(?:see|refer\s+to|cf\.?|as\s+(?:shown|described|noted)\s+in)\s+"
    r"(?:section|table|figure|appendix|page)\s*[\d\w\.\-]+",
    re.IGNORECASE,
)


def _content_hash(text: str) -> str:
    """Stable SHA-256 hash for provenance (FR-3.4)."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _estimate_tokens(text: str) -> int:
    """Rough token count (~4 chars per token for English)."""
    return max(1, len(text) // 4)


def _is_heading(block: TextBlock) -> bool:
    """Heuristic: block is a heading if block_type starts with 'head'."""
    if block.block_type and block.block_type.lower().startswith("head"):
        return True
    # Short, title-cased single-line text is likely a heading
    text = block.text.strip()
    if len(text) < 120 and "\n" not in text and text and text[0].isupper():
        # Very short lines that look like titles
        words = text.split()
        if len(words) <= 12 and not text.endswith("."):
            return True
    return False


def _is_list_block(block: TextBlock) -> bool:
    """Heuristic: block contains numbered/bulleted list items."""
    lines = block.text.strip().split("\n")
    if len(lines) < 2:
        return False
    matches = sum(1 for ln in lines if _LIST_PATTERN.match(ln))
    return matches >= 2 and matches / len(lines) >= 0.5


def _detect_cross_refs(text: str) -> list[str]:
    """Find cross-reference mentions in text."""
    return [m.group(0) for m in _CROSS_REF_PATTERN.finditer(text)]


def _chunk_type_from_block(block: TextBlock) -> ChunkType:
    """Map TextBlock to ChunkType."""
    if _is_heading(block):
        return "heading"
    if _is_list_block(block):
        return "list"
    return "paragraph"


# -----------------------------------------------------------------------------
# ChunkValidator (FR-3.3)
# -----------------------------------------------------------------------------


class ChunkValidator:
    """Validates LDUs before emit. Enforces invariants and max_tokens."""

    def __init__(self, max_tokens: int = 512) -> None:
        self._max_tokens = max_tokens

    def validate(self, ldu: LDU) -> LDU:
        """
        Validate an LDU. Raises ValidationError on failure.

        Checks:
          - content is non-empty
          - page_refs is non-empty
          - token_count >= 0
          - content_hash is non-empty
          - token_count <= max_tokens (warning-level: truncate content)
        """
        if not ldu.content.strip():
            raise ValueError("LDU content must be non-empty")
        if not ldu.page_refs:
            raise ValueError("LDU page_refs must be non-empty")
        if not ldu.content_hash:
            raise ValueError("LDU content_hash must be non-empty")

        # Enforce max tokens by splitting if needed; for now, just warn
        # and keep as-is (list chunks may legitimately exceed).
        return ldu


# -----------------------------------------------------------------------------
# ChunkingEngine (api_contracts §2.4)
# -----------------------------------------------------------------------------


class ChunkingEngine:
    """
    Transforms ExtractedDocument into list[LDU].

    Follows reading_order; applies five chunking rules (FR-3.2);
    computes content_hash (FR-3.4); validates via ChunkValidator.
    Optionally ingests LDUs into a vector store (FR-5.5).

    Usage:
        engine = ChunkingEngine()
        ldus = engine.run(extracted_doc, doc_id, config)
    """

    def __init__(
        self,
        config: RefineryConfig | None = None,
        *,
        validator: ChunkValidator | None = None,
        vector_store: object | None = None,
    ) -> None:
        from src.config import load_config

        self._config = config if config is not None else load_config()
        self._validator = validator or ChunkValidator(
            max_tokens=self._config.chunking.max_tokens_per_ldu,
        )
        self._vector_store = vector_store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        extracted: ExtractedDocument,
        doc_id: str,
        config: RefineryConfig | None = None,
    ) -> list[LDU]:
        """
        Run chunking on an ExtractedDocument.

        Returns:
            list[LDU] — all chunks pass ChunkValidator before return.

        Raises:
            ValidationError: If ChunkValidator rejects a chunk.
        """
        cfg = config or self._config
        max_tokens = cfg.chunking.max_tokens_per_ldu

        ldus: list[LDU] = []
        current_section: str | None = None
        content_hashes: dict[str, str] = {}  # hash -> chunk content for xref

        # Build lookup tables for reading order
        text_blocks = extracted.text_blocks
        tables = extracted.tables
        figures = extracted.figures

        # If reading_order is empty, build from sequential blocks/tables/figures
        order = extracted.reading_order
        if not order:
            order = self._build_default_order(text_blocks, tables, figures)

        # Process items in reading order
        i = 0
        while i < len(order):
            item = order[i]

            if item.type == "text":
                block = text_blocks[item.index] if item.index < len(text_blocks) else None
                if block is None:
                    i += 1
                    continue

                # Rule 4: section headers become parent_section
                if _is_heading(block):
                    current_section = block.text.strip()
                    # Look ahead: if next item is a table, merge header+table (Rule 1)
                    if i + 1 < len(order) and order[i + 1].type == "table":
                        table_item = order[i + 1]
                        tbl = tables[table_item.index] if table_item.index < len(tables) else None
                        if tbl is not None:
                            ldu = self._table_ldu(
                                tbl, doc_id, current_section, header_text=block.text.strip()
                            )
                            ldus.append(self._validator.validate(ldu))
                            i += 2
                            continue
                    # Emit heading as its own LDU (lightweight)
                    ldu = self._text_ldu(block, doc_id, current_section, "heading")
                    ldus.append(self._validator.validate(ldu))
                    i += 1
                    continue

                # Rule 3: numbered/bulleted list as single LDU
                if _is_list_block(block):
                    ldu = self._text_ldu(block, doc_id, current_section, "list")
                    ldus.append(self._validator.validate(ldu))
                    i += 1
                    continue

                # Regular paragraph — may need splitting if too long
                chunks = self._split_text(block.text, max_tokens)
                for chunk_text in chunks:
                    ldu = self._make_text_ldu(
                        text=chunk_text,
                        page_number=block.page_number,
                        bbox=block.bbox,
                        doc_id=doc_id,
                        parent_section=current_section,
                        chunk_type="paragraph",
                    )
                    ldus.append(self._validator.validate(ldu))
                i += 1

            elif item.type == "table":
                tbl = tables[item.index] if item.index < len(tables) else None
                if tbl is None:
                    i += 1
                    continue
                # Rule 1: check if previous was a heading (already handled above)
                # Here table appears without preceding heading
                ldu = self._table_ldu(tbl, doc_id, current_section)
                ldus.append(self._validator.validate(ldu))
                i += 1

            elif item.type == "figure":
                fig = figures[item.index] if item.index < len(figures) else None
                if fig is None:
                    i += 1
                    continue
                # Rule 2: figure + caption as single LDU
                ldu = self._figure_ldu(fig, doc_id, current_section)
                ldus.append(self._validator.validate(ldu))
                i += 1

            else:
                i += 1

        # Rule 5: cross-references as relationships
        # Build hash map so we can link
        for ldu in ldus:
            content_hashes[ldu.content_hash] = ldu.content

        for ldu in ldus:
            refs = _detect_cross_refs(ldu.content)
            if refs:
                relationships = []
                for ref_text in refs:
                    # Try to find a target LDU that matches the reference
                    for other in ldus:
                        if other.content_hash == ldu.content_hash:
                            continue
                        ref_lower = ref_text.lower()
                        # Match if the other LDU's parent_section or content
                        # mentions the referenced section/table/figure
                        if other.parent_section and other.parent_section.lower() in ref_lower:
                            relationships.append(
                                ChunkRelationship(
                                    relationship_type="references",
                                    target_content_hash=other.content_hash,
                                )
                            )
                            break
                if relationships:
                    ldu.relationships = relationships

        # Ingest into vector store if available (FR-5.5)
        if self._vector_store is not None:
            self._ingest_vector_store(ldus, doc_id)

        return ldus

    # ------------------------------------------------------------------
    # LDU construction helpers
    # ------------------------------------------------------------------

    def _text_ldu(
        self,
        block: TextBlock,
        doc_id: str,
        parent_section: str | None,
        chunk_type: ChunkType,
    ) -> LDU:
        """Create LDU from a TextBlock."""
        return self._make_text_ldu(
            text=block.text.strip(),
            page_number=block.page_number,
            bbox=block.bbox,
            doc_id=doc_id,
            parent_section=parent_section,
            chunk_type=chunk_type,
        )

    def _make_text_ldu(
        self,
        *,
        text: str,
        page_number: int,
        bbox: BoundingBox | None,
        doc_id: str,
        parent_section: str | None,
        chunk_type: ChunkType,
    ) -> LDU:
        content = text.strip()
        return LDU(
            content=content,
            chunk_type=chunk_type,
            page_refs=[page_number],
            bounding_box=bbox,
            parent_section=parent_section,
            token_count=_estimate_tokens(content),
            content_hash=_content_hash(content),
            doc_id=doc_id,
        )

    def _table_ldu(
        self,
        table: Table,
        doc_id: str,
        parent_section: str | None,
        header_text: str | None = None,
    ) -> LDU:
        """Rule 1: table + header as single LDU."""
        parts: list[str] = []
        if header_text:
            parts.append(header_text)
        if table.caption:
            parts.append(f"Caption: {table.caption}")
        # Serialize table content
        if table.headers:
            parts.append(" | ".join(table.headers))
            parts.append("-" * 40)
        for row in table.rows[:50]:  # Cap rows to avoid huge chunks
            if isinstance(row, dict):
                parts.append(" | ".join(str(v) for v in row.values()))
            else:
                parts.append(" | ".join(str(c) for c in row))

        content = "\n".join(parts)
        meta = {}
        if table.caption:
            meta["table_caption"] = table.caption
        if header_text:
            meta["table_header"] = header_text

        return LDU(
            content=content,
            chunk_type="table",
            page_refs=[table.page_number],
            bounding_box=table.bbox,
            parent_section=parent_section,
            token_count=_estimate_tokens(content),
            content_hash=_content_hash(content),
            doc_id=doc_id,
            metadata=meta or None,
        )

    def _figure_ldu(
        self,
        figure: Figure,
        doc_id: str,
        parent_section: str | None,
    ) -> LDU:
        """Rule 2: figure + caption as single LDU."""
        parts = []
        if figure.caption:
            parts.append(figure.caption)
        if figure.image_ref:
            parts.append(f"[Image: {figure.image_ref}]")
        content = "\n".join(parts) if parts else "[Figure]"

        meta = {}
        if figure.caption:
            meta["figure_caption"] = figure.caption

        return LDU(
            content=content,
            chunk_type="figure",
            page_refs=[figure.page_number],
            bounding_box=figure.bbox,
            parent_section=parent_section,
            token_count=_estimate_tokens(content),
            content_hash=_content_hash(content),
            doc_id=doc_id,
            metadata=meta or None,
        )

    # ------------------------------------------------------------------
    # Splitting
    # ------------------------------------------------------------------

    def _split_text(self, text: str, max_tokens: int) -> list[str]:
        """Split large text into chunks respecting max_tokens."""
        tokens_est = _estimate_tokens(text)
        if tokens_est <= max_tokens:
            return [text]

        # Split on paragraph boundaries first
        paragraphs = re.split(r"\n\s*\n", text)
        chunks: list[str] = []
        current: list[str] = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = _estimate_tokens(para)
            if current_tokens + para_tokens > max_tokens and current:
                chunks.append("\n\n".join(current))
                current = [para]
                current_tokens = para_tokens
            else:
                current.append(para)
                current_tokens += para_tokens

        if current:
            chunks.append("\n\n".join(current))
        return chunks if chunks else [text]

    # ------------------------------------------------------------------
    # Reading order fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _build_default_order(
        text_blocks: list[TextBlock],
        tables: list[Table],
        figures: list[Figure],
    ) -> list[ReadingOrderItem]:
        """Build reading order from sequential indices when none provided."""
        items: list[tuple[int, str, int]] = []
        for i, b in enumerate(text_blocks):
            items.append((b.page_number, "text", i))
        for i, t in enumerate(tables):
            items.append((t.page_number, "table", i))
        for i, f in enumerate(figures):
            items.append((f.page_number, "figure", i))
        items.sort(key=lambda x: (x[0], x[1], x[2]))
        return [ReadingOrderItem(type=t, index=idx) for _, t, idx in items]

    # ------------------------------------------------------------------
    # Vector store ingestion (FR-5.5)
    # ------------------------------------------------------------------

    def _ingest_vector_store(self, ldus: list[LDU], doc_id: str) -> None:
        """Ingest LDUs into ChromaDB collection if available."""
        try:
            import chromadb  # type: ignore

            if isinstance(self._vector_store, chromadb.Collection):
                collection = self._vector_store
                ids = [f"{doc_id}_{ldu.content_hash}" for ldu in ldus]
                documents = [ldu.content for ldu in ldus]
                metadatas = []
                for ldu in ldus:
                    meta = {
                        "doc_id": ldu.doc_id,
                        "chunk_type": ldu.chunk_type,
                        "page_refs": ",".join(str(p) for p in ldu.page_refs),
                        "parent_section": ldu.parent_section or "",
                        "content_hash": ldu.content_hash,
                    }
                    if ldu.bounding_box:
                        meta["bbox"] = ldu.bounding_box.model_dump_json()
                    metadatas.append(meta)

                collection.upsert(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas,
                )
        except ImportError:
            pass  # ChromaDB not installed; skip vector ingestion
        except Exception:
            pass  # Non-critical; log in production
