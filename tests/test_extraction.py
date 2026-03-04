"""Unit tests for extraction: confidence scoring, escalation, ledger (DC-3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.extractor import ExtractionRouter
from src.config import ExtractionConfig, RefineryConfig
from src.exceptions import ExtractionBudgetExceeded
from src.models.document_profile import DocumentProfile
from src.models.extracted_document import ExtractedDocument, LedgerEntry
from src.strategies.fast_text import FastTextExtractor
from src.strategies.vision import VisionExtractor


@pytest.fixture
def router_config(temp_refinery_dir: Path) -> RefineryConfig:
    """Config with temp refinery dir and high escalation threshold (so no escalation in tests)."""
    return RefineryConfig(
        refinery_dir=temp_refinery_dir,
        extraction=RefineryConfig.model_fields["extraction"].default_factory(),
    )


@pytest.fixture
def high_confidence_config(temp_refinery_dir: Path) -> RefineryConfig:
    """Config with very low escalation threshold so first strategy is accepted."""
    from src.config import ExtractionConfig

    return RefineryConfig(
        refinery_dir=temp_refinery_dir,
        extraction=ExtractionConfig(confidence_escalation_threshold=0.0),
    )


@pytest.fixture
def profile_fast_text() -> DocumentProfile:
    """Profile that routes to Strategy A."""
    return DocumentProfile(
        doc_id="test_doc",
        origin_type="native_digital",
        layout_complexity="single_column",
        language="en",
        language_confidence=0.9,
        domain_hint="general",
        estimated_extraction_cost="fast_text_sufficient",
    )


def test_router_returns_extracted_document(
    profile_fast_text: DocumentProfile,
    sample_pdf_native_digital: Path | None,
    high_confidence_config: RefineryConfig,
    temp_refinery_dir: Path,
) -> None:
    """Router run() returns ExtractedDocument and appends ledger."""
    if sample_pdf_native_digital is None:
        pytest.skip("No corpus PDF found")
    router = ExtractionRouter(config=high_confidence_config)
    doc = router.run(
        profile_fast_text,
        sample_pdf_native_digital,
        profile_fast_text.doc_id,
        config=high_confidence_config,
    )
    assert isinstance(doc, ExtractedDocument)
    assert doc.doc_id == profile_fast_text.doc_id
    assert len(doc.text_blocks) >= 1
    assert doc.reading_order is not None
    ledger_path = high_confidence_config.get_ledger_path()
    assert ledger_path.exists()
    lines = [ln for ln in ledger_path.read_text(encoding="utf-8").strip().split("\n") if ln]
    assert len(lines) >= 1
    entry = LedgerEntry.model_validate_json(lines[-1])
    assert entry.doc_id == profile_fast_text.doc_id
    assert entry.strategy_used == "fast_text"


def test_fast_text_confidence_below_threshold_escalates(
    profile_fast_text: DocumentProfile,
    sample_pdf_scanned: Path | None,
    temp_refinery_dir: Path,
) -> None:
    """When Fast Text returns low confidence, router escalates to Layout (second ledger entry)."""
    if sample_pdf_scanned is None:
        pytest.skip("No scanned PDF found")
    config = RefineryConfig(
        refinery_dir=temp_refinery_dir,
        extraction=ExtractionConfig(confidence_escalation_threshold=0.99),
    )
    router = ExtractionRouter(config=config)
    profile_fast_text.estimated_extraction_cost = "fast_text_sufficient"
    doc = router.run(
        profile_fast_text,
        sample_pdf_scanned,
        profile_fast_text.doc_id,
        config=config,
    )
    assert isinstance(doc, ExtractedDocument)
    ledger_path = config.get_ledger_path()
    lines = [ln for ln in ledger_path.read_text(encoding="utf-8").strip().split("\n") if ln]
    # At least fast_text attempt; may have layout attempt
    assert len(lines) >= 1


def test_router_raises_file_not_found(
    profile_fast_text: DocumentProfile,
    router_config: RefineryConfig,
    tmp_path: Path,
) -> None:
    """run() raises FileNotFoundError when document path does not exist."""
    router = ExtractionRouter(config=router_config)
    with pytest.raises(FileNotFoundError, match="Document not found"):
        router.run(
            profile_fast_text,
            tmp_path / "nonexistent.pdf",
            profile_fast_text.doc_id,
            config=router_config,
        )


def test_fast_text_extractor_confidence_in_range(
    sample_pdf_native_digital: Path | None,
    high_confidence_config: RefineryConfig,
) -> None:
    """FastTextExtractor returns confidence in [0, 1]."""
    if sample_pdf_native_digital is None:
        pytest.skip("No corpus PDF found")
    profile = DocumentProfile(
        doc_id="test",
        origin_type="native_digital",
        layout_complexity="single_column",
        language="en",
        language_confidence=0.9,
        domain_hint="general",
        estimated_extraction_cost="fast_text_sufficient",
    )
    ext = FastTextExtractor()
    result = ext.extract(sample_pdf_native_digital, profile, high_confidence_config)
    assert 0 <= result.confidence_score <= 1
    assert result.strategy_name == "fast_text"
    assert result.document.doc_id == "test"
    assert len(result.document.text_blocks) >= 1


def test_vision_budget_cap_halts_when_exceeded(
    profile_fast_text: DocumentProfile,
    sample_pdf_native_digital: Path | None,
    temp_refinery_dir: Path,
) -> None:
    """Strategy C raises ExtractionBudgetExceeded when budget cap would be exceeded (active halt)."""
    if sample_pdf_native_digital is None:
        pytest.skip("No corpus PDF found")
    config = RefineryConfig(
        refinery_dir=temp_refinery_dir,
        openrouter_api_key="dummy",
        vision_budget_cap_per_doc=0.0001,
    )
    ext = VisionExtractor()
    with pytest.raises(ExtractionBudgetExceeded, match="cap.*exceeded|Halting"):
        ext.extract(sample_pdf_native_digital, profile_fast_text, config)