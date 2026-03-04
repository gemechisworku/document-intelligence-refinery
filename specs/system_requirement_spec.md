# System Requirements Specification (SRS)
## Document Intelligence Refinery

**Version:** 1.0  
**Status:** Draft  

---

## 1. Introduction

### 1.1 Purpose

This document specifies the system requirements for the **Document Intelligence Refinery** — a production-grade, multi-stage agentic pipeline that ingests a heterogeneous corpus of unstructured documents (PDFs, Excel/CSV, Word, slide decks, images) and emits structured, queryable, spatially-indexed knowledge. It establishes the basis for agreement between stakeholders and the development team on functional behavior, quality attributes, and constraints. The SRS is the single source of truth for implementation and verification.

### 1.2 Scope

**In scope:**

- End-to-end pipeline: document ingestion → triage → structure extraction (multi-strategy with escalation) → semantic chunking → PageIndex building → query interface with provenance.
- Support for the four mandatory document classes: native digital financial reports (Class A), scanned government/legal (Class B), mixed technical assessment reports (Class C), and table-heavy structured data reports (Class D).
- All five pipeline stages with typed input/output schemas, confidence-gated escalation, and a provenance ledger.
- Validation against a provided corpus (e.g., 50 PDFs spanning the four classes) and demonstration per the defined Demo Protocol.

**Out of scope:**

- Building a generic PDF reader or a single-purpose PDF-to-text scraper.
- Support for document types or formats not specified in the challenge (e.g., real-time streaming, non-listed file formats beyond those stated).
- Deployment topology, hosting, or enterprise SSO (unless explicitly required by the challenge).

### 1.3 Definitions, Acronyms, and Abbreviations

| Term | Definition |
|------|------------|
| **LDU** | Logical Document Unit — a semantically coherent, self-contained chunk that preserves structural context (e.g., paragraph, table with header, figure with caption). |
| **PageIndex** | Hierarchical navigation structure over a document (inspired by [VectifyAI PageIndex](https://github.com/VectifyAI/PageIndex)); a tree of sections with title, page range, summaries, and child sections for LLM traversal. |
| **Provenance** | Traceability of extracted facts to source location: document name, page number, bounding box (bbox), and content hash. |
| **DocumentProfile** | Classification output of the Triage Agent: origin type, layout complexity, language, domain hint, and estimated extraction cost. |
| **ExtractedDocument** | Normalized internal representation of document content (text blocks with bbox, tables as structured objects, figures with captions, reading order) produced by any extraction strategy. |
| **ProvenanceChain** | Ordered list of source citations (document, page, bbox, content_hash) attached to every query answer. |
| **RAG** | Retrieval-Augmented Generation. |
| **VLM** | Vision Language Model (e.g., GPT-4o, Gemini Pro Vision). |
| **OCR** | Optical Character Recognition. |
| **Escalation** | Automatic retry with a higher-cost extraction strategy when confidence from a cheaper strategy falls below threshold. |

### 1.4 References

| ID | Reference |
|----|-----------|
| CHAL | [Challenge Document](../docs/challenge_document.md) — Week 3: The Document Intelligence Refinery |
| MinerU | [MinerU (OpenDataLab)](https://github.com/opendatalab/MinerU) — PDF parsing pipeline: PDF-Extract-Kit → Layout Detection → Formula/Table Recognition → Markdown |
| Docling | [Docling (IBM Research)](https://github.com/DS4SD/docling) — DoclingDocument representation; layout, reading order, tables, figures |
| PageIndex | [PageIndex (VectifyAI)](https://github.com/VectifyAI/PageIndex) — Hierarchical section index and reasoning-based retrieval |
| Chunkr | [Chunkr (YC S24)](https://github.com/lumina-ai-inc/chunkr) — RAG-optimized chunking by semantic units |
| Marker | [Marker](https://github.com/VikParuchuri/marker) — PDF-to-Markdown with layout models |
| IEEE 830 | IEEE Std 830-1998 (Recommended Practice for Software Requirements Specifications) |

### 1.5 Overview

The remainder of this document is organized as follows: **Section 2** describes the product from user and system perspectives, constraints, and assumptions. **Section 3** specifies detailed functional, interface, data, and non-functional requirements. Requirements are numbered for traceability (e.g., FR-1.1, NFR-2.1) and written to be verifiable.

---

## 2. General Description

### 2.1 Product Perspective

The Document Intelligence Refinery is a standalone pipeline that sits between raw document storage and downstream consumers (RAG, analytics, audit). It addresses three failure modes: **structure collapse** (OCR flattening layout/tables), **context poverty** (naive chunking severing logical units), and **provenance blindness** (inability to cite exact document location). The system uses an agentic pattern: attempt fast extraction first, measure confidence, and escalate to layout or vision models only when necessary. It produces structured JSON schemas, a PageIndex navigation tree, a RAG-ready vector store, SQL-queryable fact tables, and an audit trail with page references.

### 2.2 Product Functions (High-Level)

1. **Triage** — Classify each document (origin type, layout complexity, language, domain hint, extraction cost tier) and persist a DocumentProfile.
2. **Structure Extraction** — Extract content via one of three strategies (Fast Text, Layout-Aware, Vision-Augmented) with confidence-gated escalation.
3. **Semantic Chunking** — Convert raw extraction into LDUs that respect logical units (no table/caption/list splitting violations).
4. **PageIndex Building** — Build a hierarchical section tree with summaries and metadata for navigation before retrieval.
5. **Query Interface** — Expose a LangGraph agent with pageindex navigation, semantic search, and structured query; every answer includes a ProvenanceChain.

### 2.3 User Characteristics

- **Forward Deployed Engineer (FDE)** — Primary user; must deploy and tune the pipeline on client documents with minimal lead time. Requires clear strategy selection rationale and cost/quality tradeoffs.
- **Data / ML engineers** — Integrate extraction output (schemas, vectors, fact tables) into existing systems.
- **Auditors / compliance** — Use provenance and Audit Mode to verify claims against source documents.

### 2.4 General Constraints

- Pipeline must be validated against the provided corpus (four document classes, e.g., 50 PDFs).
- Extraction strategies must use the stated tooling landscape where applicable (e.g., pdfplumber/pymupdf for Fast Text; MinerU or Docling for Layout; VLM via OpenRouter for Vision).
- Thresholds for confidence and escalation must be externalized (e.g., in `extraction_rules.yaml`) and documented (e.g., in DOMAIN_NOTES.md).
- Per-document cost must be bounded by a configurable budget cap for vision strategy.
- All core models (DocumentProfile, ExtractedDocument, LDU, PageIndex, ProvenanceChain) must be defined as Pydantic schemas under `src/models/`.

### 2.5 Assumptions

- Input documents are provided as files (e.g., from a local or mounted path); real-time streaming is not required.
- API keys or credentials for external services (e.g., OpenRouter for VLM) are available in environment or configuration.
- The target corpus (e.g., data.zip) is available and contains at least one representative per document class (A–D).
- Python 3.10+ and dependency management (e.g., pyproject.toml) are the implementation environment.
- Docling’s DoclingDocument (or equivalent) can be adapted to the internal ExtractedDocument schema; MinerU or VLM output can be normalized via adapters.

---

## 3. Specific Requirements

### 3.1 Functional Requirements

#### 3.1.1 Stage 1: Triage Agent (Document Classifier)

| ID | Requirement | Verification |
|----|-------------|--------------|
| FR-1.1 | The system shall classify every document before extraction along the dimension **Origin Type** with values: `native_digital`, `scanned_image`, `mixed`, `form_fillable`. | Given a known document type, the produced DocumentProfile matches expected origin_type. |
| FR-1.2 | The system shall classify **Layout Complexity** with values: `single_column`, `multi_column`, `table_heavy`, `figure_heavy`, `mixed`. | Profile layout_complexity is correct for a set of labeled samples. |
| FR-1.3 | The system shall detect **Language** and output a language code plus confidence. | Language field is present and plausible for test documents. |
| FR-1.4 | The system shall assign a **Domain Hint** with values: `financial`, `legal`, `technical`, `medical`, `general`, used to select extraction prompt strategy. | Domain hint is present; implementation allows pluggable strategy (e.g., keyword vs VLM). |
| FR-1.5 | The system shall set **Estimated Extraction Cost** to one of: `fast_text_sufficient`, `needs_layout_model`, `needs_vision_model`. | Cost tier is consistent with origin_type and layout_complexity. |
| FR-1.6 | The system shall persist the DocumentProfile as a Pydantic-based JSON file under `.refinery/profiles/{doc_id}.json`. | File exists and validates against DocumentProfile schema. |
| FR-1.7 | Origin type detection shall use analyzable signals such as character density, embedded image ratio, and font metadata to distinguish digital vs scanned. | DocumentProfile correctly distinguishes native vs scanned for corpus samples. |

#### 3.1.2 Stage 2: Structure Extraction Layer (Multi-Strategy)

| ID | Requirement | Verification |
|----|-------------|--------------|
| FR-2.1 | The system shall implement **Strategy A — Fast Text** (low cost) using pdfplumber or pymupdf, triggered when origin_type is `native_digital` and layout_complexity is `single_column`. | For qualifying documents, Strategy A is selected and output is produced. |
| FR-2.2 | Strategy A shall apply a **confidence gate**: the page must have meaningful character stream (e.g., character count > 100 per page) and image area must not dominate (e.g., images < 50% of page area). Exact thresholds shall be defined in `extraction_rules.yaml` and documented in DOMAIN_NOTES.md. | Thresholds are externalized and documented; low-confidence pages trigger escalation. |
| FR-2.3 | The system shall implement **Strategy B — Layout-Aware** (medium cost) using MinerU or Docling, triggered when layout is multi_column, table_heavy, or mixed origin. It shall extract text blocks with bounding boxes, tables as structured JSON, figures with captions, and reading order. | For qualifying documents, Strategy B is selected; output includes bbox, tables, figures. |
| FR-2.4 | The system shall implement **Strategy C — Vision-Augmented** (high cost) using a VLM (e.g., Gemini Flash / GPT-4o-mini via OpenRouter), triggered when origin is scanned_image, or when Strategy A/B confidence is below threshold, or when handwriting is detected. | For qualifying documents, Strategy C is used; page images are passed with structured extraction prompts. |
| FR-2.5 | The system shall implement an **Escalation Guard**: Strategy A must measure extraction confidence; if confidence is LOW, the system shall automatically retry with Strategy B (or appropriate next tier) rather than passing low-quality data downstream. | Unit/integration test: low-confidence Fast Text output triggers Layout (or Vision) retry. |
| FR-2.6 | The system shall provide an **ExtractionRouter** that selects strategy based on DocumentProfile and delegates to the correct extractor, with automatic escalation on low confidence. | Router selects expected strategy for given profile; escalation path is exercised in tests. |
| FR-2.7 | All extraction strategies shall produce output normalized to a single internal **ExtractedDocument** schema (text blocks with bbox, tables as structured objects, figures with captions, reading order). Adapters shall normalize MinerU, Docling, or VLM output to this schema. | ExtractedDocument instances validate; adapters exist for each strategy output. |
| FR-2.8 | The system shall log every extraction in `.refinery/extraction_ledger.jsonl` with at least: strategy_used, confidence_score, cost_estimate, processing_time. | Ledger file contains required fields for each run. |
| FR-2.9 | The system shall enforce a **budget_guard** for Strategy C: track token spend per document and disallow exceeding a configurable budget cap. | Configurable cap exists; document exceeding cap is rejected or truncated with log. |

#### 3.1.3 Stage 3: Semantic Chunking Engine

| ID | Requirement | Verification |
|----|-------------|--------------|
| FR-3.1 | The system shall convert ExtractedDocument into a list of **Logical Document Units (LDUs)**. Each LDU shall carry: content, chunk_type, page_refs, bounding_box, parent_section, token_count, content_hash. | LDU schema and ChunkingEngine output comply. |
| FR-3.2 | The system shall enforce **Chunking Rules**: (1) A table cell is never split from its header row. (2) A figure caption is always stored as metadata of its parent figure chunk. (3) A numbered list is kept as a single LDU unless it exceeds max_tokens. (4) Section headers are stored as parent metadata on all child chunks in that section. (5) Cross-references (e.g., "see Table 3") are resolved and stored as chunk relationships. | ChunkValidator or equivalent verifies no rule is violated before emitting chunks. |
| FR-3.3 | The system shall implement a **ChunkValidator** that verifies no chunking rule is violated before emitting chunks. | Validator rejects or corrects violating chunks in tests. |
| FR-3.4 | The system shall generate a **content_hash** for each LDU (e.g., spatial/content hashing) to support provenance verification when document pages shift. | Each LDU has content_hash; format is documented. |
| FR-3.5 | The ChunkingEngine shall accept ExtractedDocument and emit List[LDU]. | Interface and types are implemented and tested. |

#### 3.1.4 Stage 4: PageIndex Builder

| ID | Requirement | Verification |
|----|-------------|--------------|
| FR-4.1 | The system shall build a **PageIndex** tree over each document. Each node shall represent a Section with: title, page_start, page_end, child_sections, key_entities (optional), summary (LLM-generated, 2–3 sentences), data_types_present (tables, figures, equations, etc.). | PageIndex schema and builder output comply. |
| FR-4.2 | The system shall support **PageIndex query**: given a topic string, traverse the tree to return the top-K (e.g., top-3) most relevant sections before vector search. | Query returns relevant sections; retrieval precision can be measured with/without PageIndex. |
| FR-4.3 | The system shall persist PageIndex trees (e.g., under `.refinery/pageindex/`) as JSON. | Artifacts exist for at least 12 corpus documents (min 3 per class). |

#### 3.1.5 Stage 5: Query Interface Agent

| ID | Requirement | Verification |
|----|-------------|--------------|
| FR-5.1 | The system shall provide a **LangGraph agent** with three tools: **pageindex_navigate** (tree traversal), **semantic_search** (vector retrieval), **structured_query** (SQL over extracted fact tables). | Agent exposes the three tools; each tool is callable and returns expected structure. |
| FR-5.2 | Every answer from the Query Agent shall include a **ProvenanceChain**: list of source citations with document_name, page_number, bbox, and content_hash. | Sample Q&A outputs include ProvenanceChain; format is validated. |
| FR-5.3 | The system shall implement a **FactTable** extractor for financial/numerical documents: extract key-value facts (e.g., revenue, date) into a SQLite table for precise querying. | Fact table exists and is queryable via structured_query. |
| FR-5.4 | The system shall support **Audit Mode**: given a claim (e.g., "The report states revenue was $4.2B in Q3"), the system shall either verify with a source citation or flag as "not found / unverifiable". | Audit Mode returns verify or unverifiable with citation when found. |
| FR-5.5 | The system shall ingest LDUs into a vector store (e.g., ChromaDB or FAISS) for semantic_search. | Vector store is populated and semantic_search returns relevant chunks. |

#### 3.1.6 Corpus and Validation

| ID | Requirement | Verification |
|----|-------------|--------------|
| FR-6.1 | The pipeline shall successfully process documents from **all four document classes**: Class A (native digital annual report), Class B (scanned government/legal), Class C (mixed technical assessment), Class D (table-heavy structured data). | At least one document per class is processed end-to-end; extraction and PageIndex artifacts are produced. |
| FR-6.2 | The system shall support the provided corpus format (e.g., 50 PDFs in data.zip) and produce the deliverables specified for interim and final submission (profiles, ledger, pageindex, example Q&A with ProvenanceChain). | Deliverables checklist is satisfied. |

### 3.2 Interface Requirements

| ID | Requirement | Verification |
|----|-------------|--------------|
| IR-1 | Document input shall be via file path (local or mounted). Supported formats shall include at least: PDF (native and scanned), and optionally Excel/CSV, Word, slide decks, images as stated in the challenge. | Pipeline accepts file path and processes at least PDF. |
| IR-2 | Configuration for extraction thresholds, budget cap, and chunking rules shall be externalized (e.g., `rubric/extraction_rules.yaml` or equivalent). | Changes to YAML affect behavior without code change. |
| IR-3 | External services (e.g., OpenRouter for VLM) shall be configured via environment variables or config file; no credentials shall be hardcoded. | Credentials are not in source; config is documented. |

### 3.3 Data Requirements

| ID | Requirement | Verification |
|----|-------------|--------------|
| DR-1 | The following Pydantic models shall be defined under `src/models/`: **DocumentProfile**, **ExtractedDocument**, **LDU**, **PageIndex** (tree node/section), **ProvenanceChain**. | Schemas exist and are used across pipeline stages. |
| DR-2 | Bounding box coordinates shall be serializable and consistent with a defined coordinate system (e.g., pdfplumber-style bbox); provenance shall support page ref and bbox for audit. | Bbox format is documented; citations can be mapped back to PDF. |
| DR-3 | Extraction ledger entries (extraction_ledger.jsonl) shall be append-only and include strategy_used, confidence_score, cost_estimate, processing_time. | Schema and sample entries are validated. |

### 3.4 Behavioral Requirements

| ID | Requirement | Verification |
|----|-------------|--------------|
| BR-1 | Pipeline execution order shall be: Triage → Structure Extraction (with escalation) → Semantic Chunking → PageIndex Building. Query Interface may run after ingestion. | Execution order is enforced (e.g., by pipeline orchestrator or script). |
| BR-2 | On extraction confidence below threshold, the system shall escalate to the next strategy without requiring manual intervention. | Escalation is automatic in tests. |
| BR-3 | When budget cap is exceeded for a document (Strategy C), the system shall not proceed with further VLM calls for that document and shall log the event. | Budget guard behavior is tested. |

### 3.5 Design Constraints

| ID | Requirement | Verification |
|----|-------------|--------------|
| DC-1 | Core agents and strategies shall be implemented as specified: `src/agents/triage.py`, `src/strategies/` (FastTextExtractor, LayoutExtractor, VisionExtractor), `src/agents/extractor.py` (ExtractionRouter), `src/agents/chunker.py`, `src/agents/indexer.py`, `src/agents/query_agent.py`. | File layout matches challenge deliverables. |
| DC-2 | Project shall include `pyproject.toml` with locked dependencies and README with setup and run instructions. | Dependency list and README are present and accurate. |
| DC-3 | Unit tests shall cover Triage Agent classification and extraction confidence scoring. | Tests exist and pass. |

### 3.6 Non-Functional Requirements

| ID | Requirement | Verification |
|----|-------------|--------------|
| NFR-1 | **Traceability**: Every pipeline stage shall consume and produce typed schemas (Pydantic) so that data flow is traceable from input document to ProvenanceChain. | Types are used end-to-end; no untyped dict-only handoffs at stage boundaries. |
| NFR-2 | **Observability**: Extraction strategy selection, confidence scores, and cost estimates shall be logged (extraction_ledger.jsonl) for every document. | Ledger is populated and queryable. |
| NFR-3 | **Configurability**: Confidence thresholds, budget cap, and chunking limits shall be configurable without code changes. | Documented config keys control behavior. |
| NFR-4 | **Reproducibility**: DocumentProfile and extraction strategy selection shall be deterministic for the same document and configuration. | Re-running on same document yields same profile and strategy. |
| NFR-5 | **Demo Protocol**: The system shall support the Demo Protocol sequence: (1) Triage — show DocumentProfile and strategy selection; (2) Extraction — show output and ledger; (3) PageIndex — tree navigation; (4) Query with Provenance — answer with ProvenanceChain and verification against source PDF. | Demo steps can be performed on a held-out or new document. |

---

## 4. Requirement Traceability

- **Challenge mapping**: All functional requirements trace to sections 4 (Architecture), 5 (Implementation Curriculum), 6 (Target Corpus), and 7 (Demo Protocol) of the challenge document.
- **Source mapping**: Concepts from MinerU, Docling, PageIndex, Chunkr, and Marker are reflected in FR-2.x (extraction strategies, normalized schema), FR-3.x (semantic/LDU chunking), and FR-4.x (PageIndex tree).
- **Deliverables**: Interim and final deliverable lists in the challenge map to DR-1, DC-1, DC-2, DC-3, FR-1.6, FR-2.8, FR-4.3, FR-5.2, FR-6.2.

---

## 5. Glossary (Additional Terms)

- **Agentic OCR pattern**: Try fast text extraction first; measure confidence; escalate to layout or vision model when below threshold.
- **DoclingDocument**: Unified document representation in Docling (structure, text, tables, figures in one traversable object).
- **Logical document unit (LDU)**: Same as LDU in 1.3; used in chunking literature and Chunkr-style RAG.
- **Spatial provenance**: Addressing of content by page and bounding box so that citations remain valid for audit.

---

*End of System Requirements Specification*
