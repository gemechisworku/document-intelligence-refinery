# Functional Requirements
## Document Intelligence Refinery — Use-Case & Feature View

**Version:** 1.0  
**Status:** Draft  
This document provides a **drill-down and use-case view** of the Refinery’s functional requirements. It does not introduce new requirements; it restates and organizes requirements from the [System Requirements Specification](system_requirement_spec.md) (SRS) by actor, feature area, and scenario. It must not contradict the SRS. Implementation and verification remain traceable to SRS requirement IDs. Component mappings align with [system_architecture.md](system_architecture.md).

---

## 1. Introduction

### 1.1 Purpose

- **Use-case view**: Describe what users (FDE, data engineer, auditor) can do with the system and under what conditions.
- **Feature drill-down**: Group required behavior by pipeline stage and feature area with acceptance-oriented scenarios.
- **Traceability**: Link each capability to SRS requirement IDs (FR, IR, DR, BR) and to the components that realize it (system_architecture).

### 1.2 Relationship to Other Specs

| Spec | Relationship |
|------|--------------|
| **SRS** | Authoritative source of requirements. This document restates and organizes SRS content; any conflict is resolved in favor of the SRS. |
| **_meta** | Functional_requirements is the optional “drill-down or use-case view” (_meta §1). |
| **system_architecture.md** | Components listed here are those defined in the architecture; no new components are introduced. |
| **api_contracts.md** | Interfaces and schemas referenced here are specified in api_contracts. |

### 1.3 References

| ID | Document |
|----|----------|
| SRS | [system_requirement_spec.md](system_requirement_spec.md) |
| _meta | [_meta.md](_meta.md) |
| system_architecture | [system_architecture.md](system_architecture.md) |
| api_contracts | [api_contracts.md](api_contracts.md) |

---

## 2. Actors

| Actor | Description | Primary use cases |
|-------|-------------|--------------------|
| **Forward Deployed Engineer (FDE)** | Deploys and tunes the pipeline on client documents; needs clear strategy selection and cost/quality tradeoffs. | Run ingestion, interpret DocumentProfile and strategy choice, tune config, run Demo Protocol. |
| **Data / ML engineer** | Integrates extraction output into existing systems. | Consume profiles, ExtractedDocument/LDUs, PageIndex, vector store, fact tables. |
| **Auditor / compliance** | Verifies claims against source documents. | Query with provenance, use Audit Mode to verify or flag claims. |

Defined in SRS §2.3; no additional actors.

---

## 3. Functional Requirements by Feature Area

### 3.1 Document Triage (Classification)

**Capability:** The system classifies every document before extraction so that the correct extraction strategy and cost tier can be chosen.

**Component:** Triage Agent (`src/agents/triage.py`).

| # | Requirement summary | SRS IDs | Acceptance / scenario |
|---|----------------------|---------|------------------------|
| 1 | Classify **origin type**: `native_digital`, `scanned_image`, `mixed`, `form_fillable` using character density, image ratio, font metadata. | FR-1.1, FR-1.7 | Given a known native PDF, profile has `origin_type: native_digital`; given a scanned PDF, `origin_type: scanned_image`. |
| 2 | Classify **layout complexity**: `single_column`, `multi_column`, `table_heavy`, `figure_heavy`, `mixed`. | FR-1.2 | For a multi-column annual report, profile has appropriate layout_complexity. |
| 3 | Detect **language** (code + confidence). | FR-1.3 | Language field present and plausible for corpus documents. |
| 4 | Assign **domain hint**: `financial`, `legal`, `technical`, `medical`, `general` (pluggable classifier). | FR-1.4 | Domain hint present; implementation allows swapping keyword vs VLM classifier. |
| 5 | Set **estimated extraction cost**: `fast_text_sufficient`, `needs_layout_model`, `needs_vision_model`. | FR-1.5 | Cost tier consistent with origin_type and layout_complexity. |
| 6 | Persist **DocumentProfile** as JSON under `.refinery/profiles/{doc_id}.json`. | FR-1.6 | File exists and validates against DocumentProfile schema. |

**Use case (FDE):** As an FDE, I can run triage on a document and get a DocumentProfile so that I understand which extraction strategy will be used and why.

---

### 3.2 Structure Extraction (Multi-Strategy with Escalation)

**Capability:** The system extracts document content (text, tables, figures, reading order) using one of three strategies, with confidence-gated escalation so that low-quality extraction does not proceed downstream.

**Components:** ExtractionRouter (`src/agents/extractor.py`), FastTextExtractor, LayoutExtractor, VisionExtractor (`src/strategies/`).

| # | Requirement summary | SRS IDs | Acceptance / scenario |
|---|----------------------|---------|------------------------|
| 1 | **Strategy A — Fast Text**: pdfplumber/pymupdf when `native_digital` and `single_column`. | FR-2.1 | For qualifying document, Strategy A is selected and ExtractedDocument is produced. |
| 2 | **Confidence gate** for Strategy A: character count and image area thresholds from `extraction_rules.yaml`; low confidence triggers escalation. | FR-2.2 | Thresholds externalized; low-confidence run escalates to Strategy B. |
| 3 | **Strategy B — Layout**: MinerU or Docling when multi_column, table_heavy, or mixed; output includes bbox, tables, figures, reading order. | FR-2.3 | For qualifying document, Strategy B selected; output has structured tables and bbox. |
| 4 | **Strategy C — Vision**: VLM via OpenRouter when scanned_image, or when A/B confidence &lt; threshold; budget_guard per document. | FR-2.4, FR-2.9 | For scanned doc or low confidence, Strategy C used; budget cap enforced and logged. |
| 5 | **Escalation guard**: Strategy A measures confidence; if LOW, automatic retry with B (then C if needed). | FR-2.5, BR-2 | Test: low-confidence Fast Text triggers Layout (or Vision) without manual step. |
| 6 | **ExtractionRouter** selects strategy from DocumentProfile and delegates; supports escalation. | FR-2.6 | Router choice matches profile; escalation path covered by tests. |
| 7 | All strategies produce **ExtractedDocument**; adapters normalize MinerU/Docling/VLM output. | FR-2.7 | ExtractedDocument validates; adapters exist for each strategy output. |
| 8 | Log each extraction in `.refinery/extraction_ledger.jsonl` (strategy_used, confidence_score, cost_estimate, processing_time). | FR-2.8 | Ledger has required fields per run. |

**Use case (FDE):** As an FDE, I can run extraction and see which strategy was used and the confidence score so that I can explain cost/quality tradeoffs to the client.

---

### 3.3 Semantic Chunking (LDUs)

**Capability:** The system converts raw extraction into Logical Document Units (LDUs) that respect semantic boundaries (no table/caption/list splitting) and carry provenance metadata for RAG and audit.

**Components:** ChunkingEngine (`src/agents/chunker.py`), ChunkValidator.

| # | Requirement summary | SRS IDs | Acceptance / scenario |
|---|----------------------|---------|------------------------|
| 1 | Convert ExtractedDocument → **List[LDU]**; each LDU has content, chunk_type, page_refs, bounding_box, parent_section, token_count, content_hash. | FR-3.1, FR-3.5 | ChunkingEngine accepts ExtractedDocument and returns List[LDU] with all fields. |
| 2 | Enforce **chunking rules**: table with header intact; figure caption as parent metadata; numbered list as single LDU (or split only if &gt; max_tokens); section headers as parent metadata; cross-refs as chunk relationships. | FR-3.2 | ChunkValidator verifies no rule violated before emitting. |
| 3 | **ChunkValidator** checks rules before emitting chunks. | FR-3.3 | Validator rejects or corrects violating chunks in tests. |
| 4 | Assign **content_hash** per LDU for provenance verification. | FR-3.4 | Each LDU has content_hash; format documented. |

**Use case (Data engineer):** As a data engineer, I can consume LDUs with stable content_hash and page_refs so that I can build RAG or analytics with verifiable provenance.

---

### 3.4 PageIndex (Hierarchical Navigation)

**Capability:** The system builds a hierarchical “table of contents” over each document (PageIndex) so that retrieval can navigate to relevant sections before vector search.

**Components:** PageIndex Builder (`src/agents/indexer.py`).

| # | Requirement summary | SRS IDs | Acceptance / scenario |
|---|----------------------|---------|------------------------|
| 1 | Build **PageIndex** tree; each node: title, page_start, page_end, child_sections, key_entities (optional), summary (LLM 2–3 sentences), data_types_present. | FR-4.1 | PageIndex schema and builder output comply. |
| 2 | **PageIndex query**: given topic string, return top-K (e.g., top-3) relevant sections. | FR-4.2 | Query returns relevant sections; precision measurable with/without PageIndex. |
| 3 | Persist PageIndex trees under `.refinery/pageindex/` as JSON. | FR-4.3 | At least 12 corpus docs (min 3 per class) have PageIndex artifacts. |

**Use case (FDE):** As an FDE, I can show the PageIndex tree and navigate to a specific fact without vector search, per Demo Protocol step 3.

---

### 3.5 Query Interface (Agent + Provenance)

**Capability:** The system answers natural language questions over ingested documents using PageIndex, vector search, and structured fact tables, and attaches a ProvenanceChain to every answer. It supports Audit Mode to verify or refute claims.

**Components:** Query Agent (`src/agents/query_agent.py`), vector store (ChromaDB/FAISS), SQLite (fact tables).

| # | Requirement summary | SRS IDs | Acceptance / scenario |
|---|----------------------|---------|------------------------|
| 1 | **LangGraph agent** with three tools: **pageindex_navigate**, **semantic_search**, **structured_query**. | FR-5.1 | Each tool callable and returns expected structure. |
| 2 | Every answer includes **ProvenanceChain**: document_name, page_number, bbox, content_hash. | FR-5.2 | Sample Q&A outputs include ProvenanceChain; format validated. |
| 3 | **FactTable** extractor populates SQLite; **structured_query** runs SQL over it. | FR-5.3 | Fact table exists and is queryable via structured_query. |
| 4 | **Audit Mode**: given a claim, return verification with citation or “not found / unverifiable”. | FR-5.4 | Audit Mode returns verify or unverifiable with citation when found. |
| 5 | LDUs ingested into vector store for **semantic_search**. | FR-5.5 | Vector store populated; semantic_search returns relevant chunks. |

**Use case (Auditor):** As an auditor, I can ask “Where does it say X?” and get an answer with page and bbox citations, or use Audit Mode to verify a specific claim against the source PDF.

---

### 3.6 Corpus Support and Deliverables

**Capability:** The pipeline supports the four document classes and produces all required artifacts for interim and final submission.

| # | Requirement summary | SRS IDs | Acceptance / scenario |
|---|----------------------|---------|------------------------|
| 1 | Process **all four document classes**: Class A (native digital annual report), B (scanned government/legal), C (mixed technical assessment), D (table-heavy structured data). | FR-6.1 | At least one document per class processed end-to-end with extraction and PageIndex. |
| 2 | Support corpus format (e.g., 50 PDFs in data.zip) and produce profiles, ledger, pageindex, example Q&A with ProvenanceChain per deliverables. | FR-6.2 | Deliverables checklist satisfied. |

---

### 3.7 Interfaces and Configuration

**Capability:** Document input, configuration, and external services are defined so that the system is configurable and secure.

| # | Requirement summary | SRS IDs | Acceptance / scenario |
|---|----------------------|---------|------------------------|
| 1 | Document input via **file path** (local or mounted); at least PDF (native + scanned). | IR-1 | Pipeline accepts file path and processes PDF. |
| 2 | **Configuration** (thresholds, budget cap, chunking rules) externalized in YAML (e.g., `rubric/extraction_rules.yaml`). | IR-2, NFR-3 | Changing YAML changes behavior without code change. |
| 3 | **External services** (e.g., OpenRouter) configured via env or config; no hardcoded credentials. | IR-3 | Credentials not in source; documented in README/.env.example. |

---

### 3.8 Pipeline Behavior and Data

**Capability:** Pipeline order is enforced; escalation and budget guard behave as specified; data models and artifacts are consistent.

| # | Requirement summary | SRS IDs | Acceptance / scenario |
|---|----------------------|---------|------------------------|
| 1 | **Pipeline order**: Triage → Extraction (with escalation) → Chunking → PageIndex; Query after ingestion. | BR-1 | Orchestrator enforces order. |
| 2 | **Escalation** automatic on low confidence; **budget guard** stops VLM and logs when cap exceeded. | BR-2, BR-3 | Tests cover escalation and budget guard. |
| 3 | **Pydantic models** in `src/models/`: DocumentProfile, ExtractedDocument, LDU, PageIndex, ProvenanceChain. | DR-1 | Schemas exist and used across stages. |
| 4 | **Bounding box** format consistent and documented; provenance supports page + bbox for audit. | DR-2 | Citations mappable back to PDF. |
| 5 | **Extraction ledger** append-only JSONL with strategy_used, confidence_score, cost_estimate, processing_time. | DR-3 | Ledger schema and sample entries validated. |

---

## 4. Demo Protocol (Use Case)

**Capability:** The system supports the Demo Protocol so that an FDE can demonstrate the Refinery on a held-out or new document (NFR-5).

| Step | Action | SRS / verification |
|------|--------|---------------------|
| 1. **Triage** | Drop document; show DocumentProfile; explain classification and chosen extraction strategy. | FR-1.x, FR-2.6 |
| 2. **Extraction** | Show extraction output beside original; show one table as structured JSON; show extraction_ledger entry with confidence. | FR-2.x, FR-2.8 |
| 3. **PageIndex** | Show PageIndex tree; navigate to locate specific information without vector search. | FR-4.1, FR-4.2 |
| 4. **Query with Provenance** | Ask natural language question; show answer and ProvenanceChain (page + bbox); open PDF and verify. | FR-5.1, FR-5.2 |

**Use case (FDE):** As an FDE, I can run the four-step Demo Protocol on a new document so that I can prove the pipeline works and explain strategy selection and provenance to the client.

---

## 5. Traceability

### 5.1 SRS → This Document

Every functional requirement in the SRS (§3.1–§3.6, §3.2–§3.5) is covered in §3–§4 above under the corresponding feature area or Demo Protocol step. Non-functional requirements (NFR-1–NFR-5) are referenced where they affect acceptance (e.g., NFR-3 in §3.7, NFR-5 in §4).

### 5.2 This Document → Architecture

| Feature area | Primary components (system_architecture §3) |
|--------------|---------------------------------------------|
| Triage | Triage Agent |
| Extraction | ExtractionRouter, FastTextExtractor, LayoutExtractor, VisionExtractor |
| Chunking | ChunkingEngine, ChunkValidator |
| PageIndex | PageIndex Builder |
| Query | Query Agent, pageindex_navigate, semantic_search, structured_query; Vector Store, SQLite |

### 5.3 This Document → api_contracts

Exact input/output types, schema fields, config shape, and ledger format are not restated here; they are specified in [api_contracts.md](api_contracts.md). This document references “DocumentProfile”, “ExtractedDocument”, “LDU”, “PageIndex”, “ProvenanceChain”, and “extraction_ledger” as defined there and in the SRS.

---

*End of Functional Requirements*
