"""
Unit tests for Phase 4: QueryAgent, tools, and FactTableExtractor.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.agents.fact_extractor import FactTableExtractor
from src.agents.query_agent import QueryAgent
from src.config import RefineryConfig
from src.models.extracted_document import ExtractedDocument, Table
from src.models.provenance import QueryResponse, AuditResult


@pytest.fixture
def fact_extractor(temp_refinery_dir: Path) -> FactTableExtractor:
    config = RefineryConfig(refinery_dir=temp_refinery_dir)
    return FactTableExtractor(config=config)


@pytest.fixture
def sample_table_doc() -> ExtractedDocument:
    return ExtractedDocument(
        doc_id="finance_doc1",
        text_blocks=[],
        tables=[
            Table(
                headers=["Metric", "Value"],
                rows=[
                    ["Revenue", "$10M"],
                    ["Profit", "$2M"],
                    {"Metric": "Costs", "Value": "$8M"}
                ],
                page_number=1,
                caption="Annual Financials"
            )
        ],
        figures=[],
        reading_order=[],
    )


def test_fact_table_extractor_inserts_facts(
    fact_extractor: FactTableExtractor,
    sample_table_doc: ExtractedDocument,
    temp_refinery_dir: Path,
) -> None:
    # Act
    num_facts = fact_extractor.run(sample_table_doc, "finance_doc1")
    assert num_facts == 4  # Revenue, Profit, Metric=Costs, Value=$8M
    
    # Assert
    res = fact_extractor.query("SELECT * FROM facts")
    assert len(res) == 4
    
    # Check specific fact
    res_prof = fact_extractor.query("SELECT fact_value FROM facts WHERE fact_key = 'Profit'")
    assert res_prof[0]["fact_value"] == "$2M"


def test_query_agent_fallback_no_llm(temp_refinery_dir: Path) -> None:
    config = RefineryConfig(refinery_dir=temp_refinery_dir)
    # With no openrouter key, it should fallback gracefully
    agent = QueryAgent(config=config)
    res = agent.run("What is the revenue?")
    assert "No LLM configured" in res.answer
    assert isinstance(res, QueryResponse)

    audit = agent.verify_claim("Revenue is 10M")
    assert not audit.verified
    assert "No LLM configured" in audit.message
    assert isinstance(audit, AuditResult)


def test_query_agent_semantic_search_tool_no_vector_store(temp_refinery_dir: Path) -> None:
    config = RefineryConfig(refinery_dir=temp_refinery_dir)
    agent = QueryAgent(config=config)
    # The tools are nested inside __init__ as closures
    semantic_search = agent._tools[1]
    res = semantic_search.invoke({"query": "test"})
    assert isinstance(res, list)
    assert "error" in res[0]
    assert "Vector store not configured" in res[0]["error"]


def test_query_agent_structured_query_tool(
    fact_extractor: FactTableExtractor,
    sample_table_doc: ExtractedDocument,
    temp_refinery_dir: Path,
) -> None:
    fact_extractor.run(sample_table_doc, "finance_doc1")
    config = RefineryConfig(refinery_dir=temp_refinery_dir)
    agent = QueryAgent(config=config)
    
    # Replace the extractor to use the populated one
    agent._fact_extractor = fact_extractor
    structured_query = agent._tools[2]
    
    # Invoke
    res = structured_query.invoke({"sql_query": "SELECT fact_value FROM facts WHERE fact_key = 'Revenue'"})
    assert isinstance(res, list)
    assert res[0]["fact_value"] == "$10M"

