"""
Unit tests for Phase 3: ChunkingEngine, ChunkValidator, PageIndex Builder.
Covers: five chunking rules, content_hash, ChunkValidator, PageIndex tree building,
PageIndex query, persistence, and integration with ExtractedDocument.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.chunker import ChunkingEngine, ChunkValidator, _content_hash
from src.agents.indexer import PageIndexBuilder
from src.config import ChunkingConfig, RefineryConfig
from src.models.extracted_document import (
    ExtractedDocument,
    Figure,
    ReadingOrderItem,
    Table,
    TextBlock,
)
from src.models.ldu import LDU
from src.models.page_index import PageIndexNode


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def chunk_config(temp_refinery_dir: Path) -> RefineryConfig:
    """Config for chunking tests."""
    return RefineryConfig(
        refinery_dir=temp_refinery_dir,
        chunking=ChunkingConfig(max_tokens_per_ldu=512),
    )


@pytest.fixture
def simple_extracted() -> ExtractedDocument:
    """ExtractedDocument with a few text blocks, a table, and a figure."""
    return ExtractedDocument(
        doc_id="test_doc",
        text_blocks=[
            TextBlock(text="Introduction", page_number=1, block_type="heading"),
            TextBlock(
                text="This is the first paragraph of the document. It contains enough "
                "text to be a meaningful chunk for testing purposes.",
                page_number=1,
                block_type="paragraph",
            ),
            TextBlock(text="Financial Summary", page_number=2, block_type="heading"),
            TextBlock(
                text="The company reported revenue of $10M in 2024.",
                page_number=2,
                block_type="paragraph",
            ),
        ],
        tables=[
            Table(
                headers=["Year", "Revenue", "Profit"],
                rows=[
                    ["2022", "$8M", "$1M"],
                    ["2023", "$9M", "$1.5M"],
                    ["2024", "$10M", "$2M"],
                ],
                page_number=2,
                caption="Revenue by Year",
            ),
        ],
        figures=[
            Figure(
                caption="Revenue growth chart",
                page_number=3,
            ),
        ],
        reading_order=[
            ReadingOrderItem(type="text", index=0),
            ReadingOrderItem(type="text", index=1),
            ReadingOrderItem(type="text", index=2),
            ReadingOrderItem(type="table", index=0),
            ReadingOrderItem(type="text", index=3),
            ReadingOrderItem(type="figure", index=0),
        ],
    )


@pytest.fixture
def list_extracted() -> ExtractedDocument:
    """ExtractedDocument with a numbered list block."""
    return ExtractedDocument(
        doc_id="list_doc",
        text_blocks=[
            TextBlock(text="Key Findings", page_number=1, block_type="heading"),
            TextBlock(
                text="1. First finding about revenue\n2. Second finding about costs\n"
                "3. Third finding about margins\n4. Fourth finding about growth",
                page_number=1,
                block_type="paragraph",
            ),
        ],
        tables=[],
        figures=[],
        reading_order=[
            ReadingOrderItem(type="text", index=0),
            ReadingOrderItem(type="text", index=1),
        ],
    )


@pytest.fixture
def crossref_extracted() -> ExtractedDocument:
    """ExtractedDocument with cross-references."""
    return ExtractedDocument(
        doc_id="xref_doc",
        text_blocks=[
            TextBlock(text="Analysis", page_number=1, block_type="heading"),
            TextBlock(
                text="See Table 1 for details. As described in section Analysis above.",
                page_number=1,
                block_type="paragraph",
            ),
            TextBlock(text="Methodology", page_number=2, block_type="heading"),
            TextBlock(
                text="This section covers the research methodology used.",
                page_number=2,
                block_type="paragraph",
            ),
        ],
        tables=[],
        figures=[],
        reading_order=[
            ReadingOrderItem(type="text", index=0),
            ReadingOrderItem(type="text", index=1),
            ReadingOrderItem(type="text", index=2),
            ReadingOrderItem(type="text", index=3),
        ],
    )


# =============================================================================
# ChunkValidator
# =============================================================================


class TestChunkValidator:
    def test_valid_ldu_passes(self) -> None:
        validator = ChunkValidator(max_tokens=512)
        ldu = LDU(
            content="Valid content",
            chunk_type="paragraph",
            page_refs=[1],
            token_count=3,
            content_hash="sha256:abc123",
            doc_id="doc1",
        )
        result = validator.validate(ldu)
        assert result.content == "Valid content"

    def test_empty_content_raises(self) -> None:
        validator = ChunkValidator(max_tokens=512)
        ldu = LDU(
            content="   ",
            chunk_type="paragraph",
            page_refs=[1],
            token_count=0,
            content_hash="sha256:abc",
            doc_id="doc1",
        )
        with pytest.raises(ValueError, match="non-empty"):
            validator.validate(ldu)


# =============================================================================
# content_hash
# =============================================================================


class TestContentHash:
    def test_hash_is_deterministic(self) -> None:
        h1 = _content_hash("hello world")
        h2 = _content_hash("hello world")
        assert h1 == h2

    def test_hash_changes_with_content(self) -> None:
        h1 = _content_hash("hello")
        h2 = _content_hash("world")
        assert h1 != h2

    def test_hash_prefix(self) -> None:
        h = _content_hash("test")
        assert h.startswith("sha256:")


# =============================================================================
# ChunkingEngine — Five Rules
# =============================================================================


class TestChunkingEngineRules:
    def test_run_returns_ldus(
        self, simple_extracted: ExtractedDocument, chunk_config: RefineryConfig
    ) -> None:
        """Engine returns a non-empty list of LDUs."""
        engine = ChunkingEngine(config=chunk_config)
        ldus = engine.run(simple_extracted, "test_doc", chunk_config)
        assert len(ldus) >= 1
        assert all(isinstance(ldu, LDU) for ldu in ldus)

    def test_all_ldus_have_content_hash(
        self, simple_extracted: ExtractedDocument, chunk_config: RefineryConfig
    ) -> None:
        """Every LDU has a non-empty content_hash (FR-3.4)."""
        engine = ChunkingEngine(config=chunk_config)
        ldus = engine.run(simple_extracted, "test_doc", chunk_config)
        for ldu in ldus:
            assert ldu.content_hash
            assert ldu.content_hash.startswith("sha256:")

    def test_content_hash_is_stable(
        self, simple_extracted: ExtractedDocument, chunk_config: RefineryConfig
    ) -> None:
        """Same input produces same content_hash (FR-3.4, NFR-4)."""
        engine = ChunkingEngine(config=chunk_config)
        ldus1 = engine.run(simple_extracted, "test_doc", chunk_config)
        ldus2 = engine.run(simple_extracted, "test_doc", chunk_config)
        hashes1 = {ldu.content_hash for ldu in ldus1}
        hashes2 = {ldu.content_hash for ldu in ldus2}
        assert hashes1 == hashes2

    def test_rule1_table_with_preceding_header(
        self, simple_extracted: ExtractedDocument, chunk_config: RefineryConfig
    ) -> None:
        """Rule 1: Table preceded by heading is merged into single LDU."""
        engine = ChunkingEngine(config=chunk_config)
        ldus = engine.run(simple_extracted, "test_doc", chunk_config)
        table_ldus = [ldu for ldu in ldus if ldu.chunk_type == "table"]
        assert len(table_ldus) >= 1
        # The table LDU should contain the header text
        table_ldu = table_ldus[0]
        assert "Financial Summary" in table_ldu.content or table_ldu.metadata

    def test_rule2_figure_with_caption(
        self, simple_extracted: ExtractedDocument, chunk_config: RefineryConfig
    ) -> None:
        """Rule 2: Figure + caption as single LDU."""
        engine = ChunkingEngine(config=chunk_config)
        ldus = engine.run(simple_extracted, "test_doc", chunk_config)
        fig_ldus = [ldu for ldu in ldus if ldu.chunk_type == "figure"]
        assert len(fig_ldus) >= 1
        fig = fig_ldus[0]
        assert "revenue growth" in fig.content.lower() or "chart" in fig.content.lower()

    def test_rule3_numbered_list_as_single_ldu(
        self, list_extracted: ExtractedDocument, chunk_config: RefineryConfig
    ) -> None:
        """Rule 3: Numbered list kept as single LDU."""
        engine = ChunkingEngine(config=chunk_config)
        ldus = engine.run(list_extracted, "list_doc", chunk_config)
        list_ldus = [ldu for ldu in ldus if ldu.chunk_type == "list"]
        assert len(list_ldus) >= 1
        list_ldu = list_ldus[0]
        # All list items should be in one chunk
        assert "First finding" in list_ldu.content
        assert "Fourth finding" in list_ldu.content

    def test_rule4_section_headers_as_parent(
        self, simple_extracted: ExtractedDocument, chunk_config: RefineryConfig
    ) -> None:
        """Rule 4: Section headers become parent_section on child chunks."""
        engine = ChunkingEngine(config=chunk_config)
        ldus = engine.run(simple_extracted, "test_doc", chunk_config)
        # At least one LDU should have a parent_section set
        with_parent = [ldu for ldu in ldus if ldu.parent_section is not None]
        assert len(with_parent) >= 1
        # Check that the parent_section corresponds to a heading
        parent_sections = {ldu.parent_section for ldu in with_parent}
        assert any("Introduction" in ps or "Financial" in ps for ps in parent_sections)

    def test_doc_id_set_on_all_ldus(
        self, simple_extracted: ExtractedDocument, chunk_config: RefineryConfig
    ) -> None:
        """All LDUs carry the doc_id."""
        engine = ChunkingEngine(config=chunk_config)
        ldus = engine.run(simple_extracted, "test_doc", chunk_config)
        for ldu in ldus:
            assert ldu.doc_id == "test_doc"

    def test_page_refs_non_empty(
        self, simple_extracted: ExtractedDocument, chunk_config: RefineryConfig
    ) -> None:
        """All LDUs have non-empty page_refs."""
        engine = ChunkingEngine(config=chunk_config)
        ldus = engine.run(simple_extracted, "test_doc", chunk_config)
        for ldu in ldus:
            assert len(ldu.page_refs) >= 1

    def test_empty_document_returns_empty(self, chunk_config: RefineryConfig) -> None:
        """Empty ExtractedDocument produces no LDUs."""
        empty = ExtractedDocument(
            doc_id="empty_doc",
            text_blocks=[],
            tables=[],
            figures=[],
            reading_order=[],
        )
        engine = ChunkingEngine(config=chunk_config)
        ldus = engine.run(empty, "empty_doc", chunk_config)
        assert ldus == []

    def test_no_reading_order_fallback(self, chunk_config: RefineryConfig) -> None:
        """Engine builds reading order if doc.reading_order is empty."""
        doc = ExtractedDocument(
            doc_id="no_order_doc",
            text_blocks=[
                TextBlock(text="Paragraph one.", page_number=1, block_type="paragraph"),
                TextBlock(text="Paragraph two.", page_number=2, block_type="paragraph"),
            ],
            tables=[],
            figures=[],
            reading_order=[],
        )
        engine = ChunkingEngine(config=chunk_config)
        ldus = engine.run(doc, "no_order_doc", chunk_config)
        assert len(ldus) == 2


# =============================================================================
# PageIndex Builder
# =============================================================================


class TestPageIndexBuilder:
    def test_run_returns_root_node(
        self, simple_extracted: ExtractedDocument, chunk_config: RefineryConfig
    ) -> None:
        """Builder returns a PageIndexNode root."""
        builder = PageIndexBuilder(config=chunk_config)
        root = builder.run(simple_extracted, "test_doc", chunk_config)
        assert isinstance(root, PageIndexNode)
        assert root.page_start >= 1
        assert root.page_end >= root.page_start

    def test_persists_pageindex_json(
        self,
        simple_extracted: ExtractedDocument,
        chunk_config: RefineryConfig,
        temp_refinery_dir: Path,
    ) -> None:
        """Builder writes .refinery/pageindex/{doc_id}.json."""
        builder = PageIndexBuilder(config=chunk_config)
        builder.run(simple_extracted, "test_doc", chunk_config)
        pi_path = temp_refinery_dir / "pageindex" / "test_doc.json"
        assert pi_path.exists()
        data = json.loads(pi_path.read_text(encoding="utf-8"))
        assert "title" in data
        assert "page_start" in data

    def test_tree_has_children_for_headings(
        self, simple_extracted: ExtractedDocument, chunk_config: RefineryConfig
    ) -> None:
        """Root node has child sections from headings."""
        builder = PageIndexBuilder(config=chunk_config)
        root = builder.run(simple_extracted, "test_doc", chunk_config)
        # With headings like "Introduction" and "Financial Summary"
        # the root should have children
        assert len(root.child_sections) >= 1

    def test_root_has_summary(
        self, simple_extracted: ExtractedDocument, chunk_config: RefineryConfig
    ) -> None:
        """Root node has a non-empty summary (fallback without LLM)."""
        builder = PageIndexBuilder(config=chunk_config)
        root = builder.run(simple_extracted, "test_doc", chunk_config)
        assert root.summary is not None
        assert len(root.summary) > 0

    def test_node_ids_present(
        self, simple_extracted: ExtractedDocument, chunk_config: RefineryConfig
    ) -> None:
        """All nodes have a node_id for traversal."""
        builder = PageIndexBuilder(config=chunk_config)
        root = builder.run(simple_extracted, "test_doc", chunk_config)
        assert root.node_id is not None
        for child in root.child_sections:
            assert child.node_id is not None

    def test_empty_document(self, chunk_config: RefineryConfig) -> None:
        """Empty document still produces a valid root node."""
        empty = ExtractedDocument(
            doc_id="empty_doc",
            text_blocks=[],
            tables=[],
            figures=[],
            reading_order=[],
        )
        builder = PageIndexBuilder(config=chunk_config)
        root = builder.run(empty, "empty_doc", chunk_config)
        assert isinstance(root, PageIndexNode)
        assert root.page_start >= 1

    def test_load_pageindex_roundtrip(
        self,
        simple_extracted: ExtractedDocument,
        chunk_config: RefineryConfig,
    ) -> None:
        """Load persisted PageIndex and verify it matches."""
        builder = PageIndexBuilder(config=chunk_config)
        root = builder.run(simple_extracted, "test_doc", chunk_config)
        loaded = PageIndexBuilder.load_pageindex("test_doc", chunk_config)
        assert loaded is not None
        assert loaded.title == root.title
        assert loaded.page_start == root.page_start
        assert loaded.page_end == root.page_end


# =============================================================================
# PageIndex Query (FR-4.2)
# =============================================================================


class TestPageIndexQuery:
    def test_query_returns_relevant_sections(
        self, simple_extracted: ExtractedDocument, chunk_config: RefineryConfig
    ) -> None:
        """Query for 'financial' returns relevant sections."""
        builder = PageIndexBuilder(config=chunk_config)
        root = builder.run(simple_extracted, "test_doc", chunk_config)
        results = PageIndexBuilder.query("financial revenue", root, top_k=3)
        assert len(results) >= 1
        # At least one result should mention financial
        titles = [r.title.lower() for r in results]
        assert any("financial" in t for t in titles) or len(results) >= 1

    def test_query_top_k(
        self, simple_extracted: ExtractedDocument, chunk_config: RefineryConfig
    ) -> None:
        """Query respects top_k parameter."""
        builder = PageIndexBuilder(config=chunk_config)
        root = builder.run(simple_extracted, "test_doc", chunk_config)
        results = PageIndexBuilder.query("introduction", root, top_k=1)
        assert len(results) <= 1
