"""
Unit tests for core Pydantic schema: LDU, PageIndexNode, ProvenanceChain.
Covers enums/literals, bounding boxes, provenance fields, relationships, validators (rubric).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models import (
    BoundingBox,
    ChunkRelationship,
    ChunkType,
    LDU,
    PageIndexNode,
    ProvenanceChain,
    ProvenanceCitation,
)


# -----------------------------------------------------------------------------
# LDU
# -----------------------------------------------------------------------------


def test_ldu_minimal_valid() -> None:
    ldu = LDU(
        content="Sample paragraph.",
        chunk_type="paragraph",
        page_refs=[1],
        token_count=2,
        content_hash="sha256:abc",
        doc_id="doc1",
    )
    assert ldu.content == "Sample paragraph."
    assert ldu.chunk_type == "paragraph"
    assert ldu.page_refs == [1]
    assert ldu.content_hash == "sha256:abc"
    assert ldu.bounding_box is None
    assert ldu.parent_section is None
    assert ldu.relationships is None


def test_ldu_with_bbox_and_parent_section() -> None:
    bbox = BoundingBox(x0=10.0, top=20.0, x1=100.0, bottom=30.0)
    ldu = LDU(
        content="Section text",
        chunk_type="heading",
        page_refs=[1, 2],
        bounding_box=bbox,
        parent_section="Chapter 1",
        token_count=2,
        content_hash="h1",
        doc_id="doc1",
    )
    assert ldu.bounding_box is not None
    assert ldu.bounding_box.x0 == 10.0
    assert ldu.parent_section == "Chapter 1"


def test_ldu_chunk_type_literal() -> None:
    for ct in ("paragraph", "table", "figure", "list", "heading"):
        ldu = LDU(
            content="x",
            chunk_type=ct,
            page_refs=[1],
            token_count=1,
            content_hash="h",
            doc_id="d",
        )
        assert ldu.chunk_type == ct


def test_ldu_with_relationships() -> None:
    rel = ChunkRelationship(relationship_type="continues", target_content_hash="other_hash")
    ldu = LDU(
        content="Part one.",
        chunk_type="paragraph",
        page_refs=[1],
        token_count=2,
        content_hash="h1",
        doc_id="doc1",
        relationships=[rel],
    )
    assert ldu.relationships is not None
    assert ldu.relationships[0].target_content_hash == "other_hash"


def test_ldu_validator_page_refs_non_empty() -> None:
    with pytest.raises(ValidationError) as exc_info:
        LDU(
            content="x",
            chunk_type="paragraph",
            page_refs=[],
            token_count=0,
            content_hash="h",
            doc_id="d",
        )
    assert "page_refs" in str(exc_info.value) or "non-empty" in str(exc_info.value).lower()


def test_ldu_validator_token_count_non_negative() -> None:
    with pytest.raises(ValidationError):
        LDU(
            content="x",
            chunk_type="paragraph",
            page_refs=[1],
            token_count=-1,
            content_hash="h",
            doc_id="d",
        )


# -----------------------------------------------------------------------------
# PageIndexNode (recursive, page_start <= page_end)
# -----------------------------------------------------------------------------


def test_page_index_node_valid() -> None:
    node = PageIndexNode(
        title="Root",
        page_start=1,
        page_end=10,
        summary="Overview section.",
    )
    assert node.title == "Root"
    assert node.page_start == 1
    assert node.page_end == 10
    assert node.child_sections == []


def test_page_index_node_recursive_children() -> None:
    child = PageIndexNode(title="Child", page_start=2, page_end=5)
    root = PageIndexNode(
        title="Document",
        page_start=1,
        page_end=10,
        child_sections=[child],
    )
    assert len(root.child_sections) == 1
    assert root.child_sections[0].title == "Child"
    assert root.child_sections[0].page_start == 2
    assert root.child_sections[0].child_sections == []


def test_page_index_node_validator_page_end_ge_page_start() -> None:
    with pytest.raises(ValidationError) as exc_info:
        PageIndexNode(
            title="Bad",
            page_start=5,
            page_end=3,
        )
    assert "page" in str(exc_info.value).lower() or "error" in str(exc_info.value).lower()


def test_page_index_node_equal_start_end_allowed() -> None:
    node = PageIndexNode(title="Single", page_start=1, page_end=1)
    assert node.page_start == node.page_end


# -----------------------------------------------------------------------------
# ProvenanceChain and ProvenanceCitation
# -----------------------------------------------------------------------------


def test_provenance_citation_minimal() -> None:
    cit = ProvenanceCitation(document_name="report.pdf", page_number=3)
    assert cit.document_name == "report.pdf"
    assert cit.page_number == 3
    assert cit.bbox is None
    assert cit.content_hash is None
    assert cit.content_snippet is None


def test_provenance_citation_with_bbox_and_content_hash() -> None:
    bbox = BoundingBox(x0=0.0, top=0.0, x1=100.0, bottom=20.0)
    cit = ProvenanceCitation(
        document_name="doc",
        page_number=1,
        bbox=bbox,
        content_hash="ldu_hash_123",
        content_snippet="Exact quote.",
    )
    assert cit.bbox is not None
    assert cit.bbox.x1 == 100.0
    assert cit.content_hash == "ldu_hash_123"
    assert cit.content_snippet == "Exact quote."


def test_provenance_chain_ordered_citations() -> None:
    chain = ProvenanceChain(
        citations=[
            ProvenanceCitation(document_name="a", page_number=1),
            ProvenanceCitation(document_name="a", page_number=2, content_hash="h2"),
        ]
    )
    assert len(chain.citations) == 2
    assert chain.citations[0].page_number == 1
    assert chain.citations[1].content_hash == "h2"
