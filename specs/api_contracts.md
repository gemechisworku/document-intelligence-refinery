# API Contracts
## Document Intelligence Refinery — Interfaces, Schemas, Config & Ledger

**Version:** 1.0  
**Status:** Draft  
This document is the single source for **implementable contracts** between components: agent method signatures, Pydantic schema field lists and invariants, configuration shape, extraction ledger format, and Query Agent tool contracts. Implementation must conform to these contracts. Authority: [System Requirements Specification](system_requirement_spec.md) (SRS), [Meta](_meta.md) (_meta), [System Architecture](system_architecture.md).

---

## 1. Introduction

### 1.1 Purpose

- Define **agent interfaces**: primary method names, input and output types, side effects, and documented exceptions.
- Define **schema contracts**: required fields, types, and invariants for all cross-stage Pydantic models (DR-1).
- Define **configuration**: root config object and YAML structure for extraction rules, thresholds, and chunking.
- Define **ledger**: extraction_ledger.jsonl entry schema (FR-2.8, DR-3).
- Define **Query Agent tools**: input/output for pageindex_navigate, semantic_search, structured_query.

All cross-stage payloads use these types; no untyped dict-only handoffs at stage boundaries (NFR-1).

### 1.2 References

| ID | Document |
|----|----------|
| SRS | [system_requirement_spec.md](system_requirement_spec.md) |
| _meta | [_meta.md](_meta.md) |
| system_architecture | [system_architecture.md](system_architecture.md) |
| functional_requirements | [functional_requirements.md](functional_requirements.md) |

---

## 2. Agent Interfaces

Agents live under `src/agents/` per DC-1. Each exposes a single primary entry method. Types below are Pydantic model names or standard types; definitions are in §3.

### 2.1 Triage Agent

| Contract | Specification |
|----------|----------------|
| **Module** | `src.agents.triage` |
| **Primary method** | `run(document_path: Path | str, doc_id: str) -> DocumentProfile` |
| **Input** | `document_path`: local or mounted file path to the document. `doc_id`: unique identifier for the document (used for artifact paths). |
| **Output** | `DocumentProfile` (see §3.1). |
| **Side effects** | Writes `.refinery/profiles/{doc_id}.json` (JSON-serialized DocumentProfile). |
| **Exceptions** | `FileNotFoundError` if document_path does not exist; `ValidationError` on schema validation failure. |
| **Determinism** | Deterministic for same document and config (NFR-4). |

### 2.2 ExtractionRouter

| Contract | Specification |
|----------|----------------|
| **Module** | `src.agents.extractor` |
| **Primary method** | `run(profile: DocumentProfile, document_path: Path | str, doc_id: str, config: RefineryConfig) -> ExtractedDocument` |
| **Input** | `profile`: from Triage. `document_path`, `doc_id`: as above. `config`: extraction thresholds, budget cap, paths. |
| **Output** | `ExtractedDocument` (see §3.2). |
| **Side effects** | Appends one or more entries to `.refinery/extraction_ledger.jsonl` (see §5). May escalate and call another strategy; each attempt logged. |
| **Exceptions** | `ExtractionBudgetExceeded` when Strategy C budget cap exceeded; `FileNotFoundError`; `ValidationError`. |
| **Determinism** | Strategy selection deterministic for same profile and config (NFR-4); extraction output deterministic for same document and strategy. |

### 2.3 Extractors (Strategy Pattern)

All extractors implement a common protocol and live under `src/strategies/`. They return a **result object** that includes the normalized document and confidence (and cost for Vision).

**Protocol (base interface):**

| Contract | Specification |
|----------|----------------|
| **Method** | `extract(document_path: Path | str, profile: DocumentProfile, config: RefineryConfig) -> ExtractionResult` |
| **ExtractionResult** | Pydantic model with at least: `document: ExtractedDocument`, `confidence_score: float`, `strategy_name: str`. For Vision extractor only: `cost_estimate: float` (and optional token count). |

**Implementations:**

| Strategy | Class | Strategy name | Notes |
|----------|--------|----------------|-------|
| A | `FastTextExtractor` | `"fast_text"` | Uses pdfplumber or pymupdf; computes confidence from character count, image area, etc. |
| B | `LayoutExtractor` | `"layout"` | Uses MinerU or Docling; adapter normalizes to ExtractedDocument. |
| C | `VisionExtractor` | `"vision"` | Uses VLM via OpenRouter; enforces budget_guard; adapter normalizes VLM output. |

**Exceptions:** `ExtractionBudgetExceeded` (Vision only, when cap exceeded); `ValidationError`; tool-specific I/O or API errors.

### 2.4 ChunkingEngine

| Contract | Specification |
|----------|----------------|
| **Module** | `src.agents.chunker` |
| **Primary method** | `run(extracted: ExtractedDocument, doc_id: str, config: RefineryConfig) -> list[LDU]` |
| **Input** | `extracted`: from ExtractionRouter. `doc_id`: for vector store and fact table association. `config`: chunking rules (max_tokens, etc.). |
| **Output** | `list[LDU]` (see §3.3). All chunks must pass ChunkValidator before return. |
| **Side effects** | Writes LDUs to vector store (ChromaDB/FAISS); may populate SQLite fact table via FactTable extractor. |
| **Exceptions** | `ValidationError` if ChunkValidator rejects; dependency errors (vector store, SQLite). |
| **Determinism** | Deterministic for same ExtractedDocument and config (content_hash stable). |

### 2.5 PageIndex Builder

| Contract | Specification |
|----------|----------------|
| **Module** | `src.agents.indexer` |
| **Primary method** | `run(extracted: ExtractedDocument, doc_id: str, config: RefineryConfig) -> PageIndexNode` |
| **Input** | `extracted`: from ExtractionRouter (or equivalent structured input). `doc_id`, `config`. |
| **Output** | `PageIndexNode`: root of the PageIndex tree (see §3.4). |
| **Side effects** | Writes `.refinery/pageindex/{doc_id}.json` (JSON-serialized tree). |
| **Exceptions** | LLM/API errors for summary generation; `ValidationError`. |
| **Determinism** | May be non-deterministic due to LLM summaries. |

### 2.6 Query Agent

| Contract | Specification |
|----------|----------------|
| **Module** | `src.agents.query_agent` |
| **Primary method** | `run(question: str, doc_ids: list[str] | None = None) -> QueryResponse` |
| **Audit Mode** | `verify_claim(claim: str, doc_ids: list[str] | None = None) -> AuditResult` |
| **Input** | `question`: natural language question. `doc_ids`: optional filter by document; if None, search all ingested docs. |
| **Output** | `QueryResponse`: `answer: str`, `provenance_chain: ProvenanceChain` (see §3.5). `AuditResult`: `verified: bool`, `citation: ProvenanceCitation | None`, `message: str` (e.g. "not found / unverifiable" when not verified). |
| **Side effects** | None (read-only over PageIndex, vector store, SQLite). |
| **Tools (internal)** | pageindex_navigate, semantic_search, structured_query — see §6. |
| **Determinism** | Non-deterministic (LLM and possibly retrieval order). |

---

## 3. Schema Contracts (Pydantic Models)

All models in `src/models/` (DR-1). Fields are **required** unless marked optional. Types use Python 3.10+ syntax. Serialization: JSON via `.model_dump()` / `.model_dump_json()` (_meta §5.2).

### 3.1 BoundingBox (DR-2)

Single representation for all bbox coordinates (pdfplumber-style, in points).

| Field | Type | Description |
|-------|------|-------------|
| `x0` | `float` | Left. |
| `top` | `float` | Top. |
| `x1` | `float` | Right. |
| `bottom` | `float` | Bottom. |

**Invariant:** `x0 <= x1`, `top <= bottom`. Coordinate system: origin top-left, units in points (1/72 inch). Use a Pydantic model or type alias so all schemas reference the same type.

### 3.2 DocumentProfile

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `doc_id` | `str` | Yes | Document identifier. |
| `origin_type` | `Literal["native_digital", "scanned_image", "mixed", "form_fillable"]` | Yes | FR-1.1. |
| `layout_complexity` | `Literal["single_column", "multi_column", "table_heavy", "figure_heavy", "mixed"]` | Yes | FR-1.2. |
| `language` | `str` | Yes | Language code (e.g. ISO 639-1). |
| `language_confidence` | `float` | Yes | In [0, 1]. FR-1.3. |
| `domain_hint` | `Literal["financial", "legal", "technical", "medical", "general"]` | Yes | FR-1.4. |
| `estimated_extraction_cost` | `Literal["fast_text_sufficient", "needs_layout_model", "needs_vision_model"]` | Yes | FR-1.5. |

**Persisted as:** `.refinery/profiles/{doc_id}.json`.

### 3.3 ExtractedDocument

Normalized output of any extraction strategy (FR-2.7). Adapters map MinerU, Docling, and VLM output into this schema.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `doc_id` | `str` | Yes | Source document id. |
| `text_blocks` | `list[TextBlock]` | Yes | Ordered text with bbox. |
| `tables` | `list[Table]` | Yes | Tables as structured JSON (headers + rows). |
| `figures` | `list[Figure]` | Yes | Figures with captions. |
| `reading_order` | `list[ReadingOrderItem]` | Yes | Ordered references to blocks/tables/figures for reading order. |

**Nested types (minimal contract):**

- **TextBlock:** `text: str`, `page_number: int`, `bbox: BoundingBox | None`, optional `block_type` (e.g. paragraph, heading).
- **Table:** `headers: list[str]`, `rows: list[list[str] | dict]`, `page_number: int`, `bbox: BoundingBox | None`, optional `caption`.
- **Figure:** `caption: str | None`, `page_number: int`, `bbox: BoundingBox | None`, optional `image_ref` or placeholder.
- **ReadingOrderItem:** Discriminated reference (e.g. `{"type": "text", "index": int}` or `{"type": "table", "index": int}`) so consumers can reconstruct order.

### 3.4 LDU (Logical Document Unit)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | `str` | Yes | Text content of the chunk. FR-3.1. |
| `chunk_type` | `str` | Yes | E.g. `"paragraph"`, `"table"`, `"figure"`, `"list"`. |
| `page_refs` | `list[int]` | Yes | Page numbers (1-based or 0-based, document consistently). |
| `bounding_box` | `BoundingBox | None` | No | Optional; use when chunk maps to a single bbox. |
| `parent_section` | `str | None` | No | Section header or title. FR-3.2 rule 4. |
| `token_count` | `int` | Yes | Approximate token count. |
| `content_hash` | `str` | Yes | Stable hash for provenance (FR-3.4). |
| `metadata` | `dict | None` | No | E.g. figure caption, table caption, cross-refs (FR-3.2 rules 2, 5). |
| `doc_id` | `str` | Yes | Source document. |

**Invariants:** Chunking rules (FR-3.2) enforced by ChunkValidator before emit. Optional: `relationships: list[ChunkRelationship]` for cross-references.

### 3.5 PageIndexNode (Section)

Tree node for PageIndex (FR-4.1). Root is the document; children are sections.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | `str` | Yes | Section title. |
| `page_start` | `int` | Yes | First page (inclusive). |
| `page_end` | `int` | Yes | Last page (inclusive). |
| **Invariant** | — | — | `page_start <= page_end`. |
| `child_sections` | `list[PageIndexNode]` | Yes | Child nodes (recursive). |
| `key_entities` | `list[str] | None` | No | Optional named entities. |
| `summary` | `str | None` | No | LLM-generated 2–3 sentences. |
| `data_types_present` | `list[str] | None` | No | E.g. `["tables", "figures", "equations"]`. |
| `node_id` | `str | None` | No | Optional stable id for traversal. |

**Persisted as:** `.refinery/pageindex/{doc_id}.json` (root node as JSON).

### 3.6 ProvenanceChain and ProvenanceCitation

| Type | Field | Type | Required | Description |
|------|--------|------|----------|-------------|
| **ProvenanceCitation** | `document_name` | `str` | Yes | Document identifier or file name. |
| | `page_number` | `int` | Yes | Page. |
| | `bbox` | `BoundingBox | None` | No | Optional. |
| | `content_hash` | `str | None` | No | LDU content_hash when applicable. |
| | `content_snippet` | `str | None` | No | Optional short snippet for display. |
| **ProvenanceChain** | `citations` | `list[ProvenanceCitation]` | Yes | Ordered list (FR-5.2). |

**Invariant:** Citations ordered by relevance or document order as defined by implementation.

### 3.7 ExtractionResult (Extractor output)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `document` | `ExtractedDocument` | Yes | Normalized extraction. |
| `confidence_score` | `float` | Yes | In [0, 1]; used for escalation. |
| `strategy_name` | `Literal["fast_text", "layout", "vision"]` | Yes | Which strategy produced this. |
| `cost_estimate` | `float | None` | No | For Vision strategy; optional for others. |
| `processing_time_seconds` | `float | None` | No | Optional. |

---

## 4. Configuration Contract

### 4.1 RefineryConfig (root config)

Single root object loaded from YAML + environment (_meta §5.3). Injected into agents; no file reads inside agents.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `refinery_dir` | `Path | str` | Yes | Base path for `.refinery/` (profiles, pageindex, ledger). |
| `extraction` | `ExtractionConfig` | Yes | Thresholds and strategy rules. |
| `chunking` | `ChunkingConfig` | Yes | Chunking rules and limits. |
| `vision_budget_cap_per_doc` | `float` | Yes | Max token cost (or USD) per document for Strategy C (FR-2.9). |
| `openrouter_api_key` | `str | None` | No | From env; required when Strategy C is used. |
| `openrouter_model` | `str | None` | No | E.g. `"google/gemini-flash-1.5"`, `"openai/gpt-4o-mini"`. |

**Validation:** Fail fast at startup if required keys or env vars (e.g. API key when Vision enabled) are missing.

### 4.2 ExtractionConfig (and extraction_rules.yaml)

Maps to content of `rubric/extraction_rules.yaml` or equivalent (IR-2).

| Field | Type | Description |
|-------|------|-------------|
| `fast_text_min_char_count_per_page` | `int` | e.g. 100 (FR-2.2). |
| `fast_text_max_image_area_ratio` | `float` | e.g. 0.5 (images &lt; 50% of page). |
| `confidence_escalation_threshold` | `float` | Below this, escalate to next strategy (e.g. 0.6). |
| (optional) strategy selection overrides | — | Document-specific overrides if needed. |

### 4.3 ChunkingConfig

| Field | Type | Description |
|-------|------|-------------|
| `max_tokens_per_ldu` | `int` | Max tokens per LDU; numbered list can exceed as single LDU until this (FR-3.2). |
| (optional) `chunk_types` | `list[str]` | Allowed chunk_type values. |

---

## 5. Extraction Ledger Contract

**File:** `.refinery/extraction_ledger.jsonl`  
**Format:** One JSON object per line (append-only). Each line serializable from a Pydantic model (FR-2.8, DR-3).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `doc_id` | `str` | Yes | Document. |
| `strategy_used` | `str` | Yes | `"fast_text"` \| `"layout"` \| `"vision"`. |
| `confidence_score` | `float` | Yes | In [0, 1]. |
| `cost_estimate` | `float` | Yes | Numeric (tokens or USD); 0 if not applicable. |
| `processing_time` | `float` | Yes | Seconds. |
| `timestamp_utc` | `str | None` | No | ISO 8601. |
| `escalated_from` | `str | None` | No | If this run was escalation, previous strategy name. |

**Invariant:** Append-only; no in-place updates.

---

## 6. Query Agent Tool Contracts

The Query Agent invokes these tools internally. Each tool is callable and returns a typed structure.

### 6.1 pageindex_navigate

| Contract | Specification |
|----------|----------------|
| **Purpose** | Return top-K sections most relevant to a topic by traversing the PageIndex tree (FR-4.2). |
| **Input** | `topic: str`, `doc_ids: list[str] | None`, `top_k: int = 3`. |
| **Output** | `list[PageIndexNode]` or a minimal view (e.g. `list[{title, page_start, page_end, summary}]`) for the top-K sections. |

### 6.2 semantic_search

| Contract | Specification |
|----------|----------------|
| **Purpose** | Vector retrieval over LDUs (FR-5.5). |
| **Input** | `query: str`, `doc_ids: list[str] | None`, `top_k: int`. |
| **Output** | `list[LDU]` or list of items with at least `content`, `doc_id`, `page_refs`, `content_hash`, `bounding_box` for provenance. |

### 6.3 structured_query

| Contract | Specification |
|----------|----------------|
| **Purpose** | Run SQL (or natural language translated to SQL) over extracted fact tables (FR-5.3). |
| **Input** | `query: str` (SQL or natural language); optional `doc_ids`. |
| **Output** | Tabular result (e.g. list of dicts or rows) plus optional provenance (e.g. which document/fact table). |

---

## 7. Exceptions

Implementations shall use explicit exceptions (_meta §5.1). Recommended names (in `src/` or shared module):

| Exception | When |
|-----------|------|
| `ExtractionBudgetExceeded` | Strategy C per-document token/cost exceeds config cap (FR-2.9, BR-3). |
| `ValidationError` | Pydantic validation failure or ChunkValidator rejection. |
| `FileNotFoundError` | Document path or required artifact path missing. |

Docstrings of agents and strategies shall document which exceptions they raise.

---

## 8. Serialization and Wire Formats

- **JSON:** All Pydantic models use `.model_dump(mode="json")` or equivalent for artifact and ledger serialization so that types are JSON-native (no custom encoders required for standard types).
- **BoundingBox:** Serialized as `{"x0": float, "top": float, "x1": float, "bottom": float}`.
- **Artifact paths:** Profiles: `.refinery/profiles/{doc_id}.json`. PageIndex: `.refinery/pageindex/{doc_id}.json`. Ledger: `.refinery/extraction_ledger.jsonl` (single file, append).
- **Versioning:** If schema compatibility is broken, add a `version` field to the root of persisted JSON or document in DOMAIN_NOTES.md (_meta §5.2).

---

## 9. Traceability

| Contract section | SRS | Architecture |
|------------------|-----|--------------|
| §2 Agent interfaces | FR-1.6, FR-2.6, FR-2.8, FR-3.5, FR-4.1, FR-5.1–5.2, BR-1 | §3 Components, §9 Interface summary |
| §3 Schemas | DR-1, DR-2, FR-1.1–1.5, FR-2.7, FR-3.1, FR-4.1, FR-5.2 | §4 Data flow |
| §4 Config | IR-2, NFR-3, FR-2.2, FR-2.9 | — |
| §5 Ledger | FR-2.8, DR-3 | §7 Data stores |
| §6 Query tools | FR-4.2, FR-5.1, FR-5.3, FR-5.5 | §6 Query path |
| §7 Exceptions | FR-2.9, BR-3 | _meta §5.1, §7 |

---

*End of API Contracts*
