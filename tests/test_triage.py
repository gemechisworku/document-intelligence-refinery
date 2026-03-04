"""Unit tests for Triage Agent classification (DC-3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.triage import TriageAgent
from src.config import RefineryConfig
from src.models.document_profile import DocumentProfile


@pytest.fixture
def triage_agent(temp_refinery_dir: Path) -> TriageAgent:
    """Triage agent with temp refinery dir."""
    config = RefineryConfig(refinery_dir=temp_refinery_dir)
    return TriageAgent(config=config)


def test_triage_produces_valid_document_profile(
    triage_agent: TriageAgent,
    sample_pdf_native_digital: Path | None,
    temp_refinery_dir: Path,
) -> None:
    """Given a native digital PDF, run() returns a DocumentProfile that validates."""
    if sample_pdf_native_digital is None:
        pytest.skip("No corpus PDF found (data/data/)")
    doc_id = "test_fta"
    profile = triage_agent.run(sample_pdf_native_digital, doc_id)
    assert isinstance(profile, DocumentProfile)
    assert profile.doc_id == doc_id
    assert profile.origin_type in ("native_digital", "mixed")
    assert profile.layout_complexity in (
        "single_column",
        "multi_column",
        "table_heavy",
        "figure_heavy",
        "mixed",
    )
    assert profile.domain_hint in ("financial", "legal", "technical", "medical", "general")
    assert profile.estimated_extraction_cost in (
        "fast_text_sufficient",
        "needs_layout_model",
        "needs_vision_model",
    )
    assert 0 <= profile.language_confidence <= 1
    # Profile persisted
    profile_path = temp_refinery_dir / "profiles" / f"{doc_id}.json"
    assert profile_path.exists()
    reloaded = DocumentProfile.model_validate_json(profile_path.read_text())
    assert reloaded.doc_id == profile.doc_id
    assert reloaded.origin_type == profile.origin_type


def test_triage_classifies_scanned_as_scanned_image(
    triage_agent: TriageAgent,
    sample_pdf_scanned: Path | None,
) -> None:
    """Given a scanned PDF, profile has origin_type scanned_image (or mixed if sparse text)."""
    if sample_pdf_scanned is None:
        pytest.skip("No scanned corpus PDF found")
    profile = triage_agent.run(sample_pdf_scanned, "test_scanned")
    # 2018_Audited has no text stream; Audit Report has minimal text on p1
    assert profile.origin_type in ("scanned_image", "mixed")
    assert profile.estimated_extraction_cost in ("needs_layout_model", "needs_vision_model")


def test_triage_raises_file_not_found(triage_agent: TriageAgent, tmp_path: Path) -> None:
    """run() raises FileNotFoundError when document path does not exist."""
    with pytest.raises(FileNotFoundError, match="Document not found"):
        triage_agent.run(tmp_path / "nonexistent.pdf", "doc1")


def test_triage_deterministic(
    triage_agent: TriageAgent,
    sample_pdf_native_digital: Path | None,
    temp_refinery_dir: Path,
) -> None:
    """Same document + config yields same profile (NFR-4)."""
    if sample_pdf_native_digital is None:
        pytest.skip("No corpus PDF found")
    doc_id = "deterministic_test"
    p1 = triage_agent.run(sample_pdf_native_digital, doc_id)
    # Run again (overwrite profile)
    p2 = triage_agent.run(sample_pdf_native_digital, doc_id)
    assert p1.origin_type == p2.origin_type
    assert p1.layout_complexity == p2.layout_complexity
    assert p1.estimated_extraction_cost == p2.estimated_extraction_cost
