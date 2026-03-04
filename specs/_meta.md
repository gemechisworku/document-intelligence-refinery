# Meta: Technical Standards & Implementation Governance

**Document Intelligence Refinery**  
This document establishes technical standards, architectural style, tech stack, API design patterns, and other governance that apply to the entire implementation and to the system architecture. All implementation and architecture decisions shall align with the [System Requirements Specification](system_requirement_spec.md) (SRS).

---

## 1. Document Hierarchy & Authority

| Document | Role |
|----------|------|
| **system_requirement_spec.md** | *What* the system shall do; single source of truth for requirements and verification. |
| **_meta.md** (this document) | *How* we build: standards, stack, patterns, and conventions that govern implementation and architecture. |
| **api_contracts.md** | *Contracts* between components: agent interfaces (input/output types), schema summaries, config shape, and ledger formats. Implementation must conform to these contracts. |
| **system_architecture.md** | *Structure* of the system: components, data flow, and deployment view (to be created; shall conform to _meta, api_contracts, and SRS). |
| **functional_requirements.md** | Optional drill-down or use-case view; must not contradict SRS. |

Conflicts are resolved in this order: SRS > _meta > api_contracts > system_architecture > other specs.

---

## 2. Technical Standards

### 2.1 Language & Runtime

- **Language**: Python 3.10+ (type hints required on all public APIs and pipeline stage boundaries).
- **Package management**: [PEP 621](https://peps.python.org/pep-0621/) via `pyproject.toml`; dependencies shall be locked (e.g., `uv lock` or `pip-tools`).
- **Virtual environments**: Use project-local venv; document activation in README.

### 2.2 Code Quality & Style

- **Formatter**: Ruff (or Black) for formatting; line length 100 unless project config overrides.
- **Linting**: Ruff for linting; no committed code with unresolved errors from `ruff check`.
- **Type checking**: Static typing for all modules under `src/`; use `typing` and Pydantic. MyPy optional but encouraged; if used, run in CI.
- **Imports**: Absolute imports from `src` (e.g., `from src.models import DocumentProfile`); no relative imports across package boundaries. Use `__all__` for public API surfaces.
- **Naming**:
  - Files/modules: `snake_case`.
  - Classes: `PascalCase`.
  - Functions, variables, constants: `snake_case`.
  - Constants: `UPPER_SNAKE_CASE` when module-level and immutable.

### 2.3 Testing

- **Framework**: pytest.
- **Coverage**: Unit tests for Triage Agent classification and extraction confidence scoring (per DC-3); aim for coverage on agents and strategies.
- **Placement**: Tests under `tests/`; mirror `src/` layout where helpful. Use fixtures for shared document paths and mock config.
- **Naming**: `test_<module>_<behavior>.py` or `test_<class>_<method>_<scenario>.py`.

### 2.4 Documentation

- **Docstrings**: All public classes and functions must have docstrings (Google or NumPy style). Include Args, Returns, Raises where relevant.
- **README**: Setup, run instructions, and how to run the Demo Protocol (per NFR-5).
- **Domain and config**: Extraction strategy decision tree, failure modes, and pipeline diagram in DOMAIN_NOTES.md; thresholds and chunking rules in `rubric/extraction_rules.yaml` with comments.

### 2.5 Security & Secrets

- **No hardcoded credentials**: API keys (e.g., OpenRouter) and secrets come from environment variables or a config file excluded from version control (per IR-3).
- **.gitignore**: Ensure `.env`, `*.key`, and config files containing secrets are ignored.
- **Config**: Document required env vars (e.g., `OPENROUTER_API_KEY`) in README or `.env.example`.

---

## 3. Architectural Style

### 3.1 Pipeline Architecture

- **Stages**: The system is a **linear pipeline with conditional branching** inside stages:
  1. Triage (single path).
  2. Structure Extraction (multi-strategy with confidence-gated escalation).
  3. Semantic Chunking (single path).
  4. PageIndex Building (single path).
  5. Query Interface (used after ingestion; not part of the ingestion pipeline order per BR-1).

- **Data flow**: Each stage consumes **typed inputs** and produces **typed outputs** (Pydantic models). No untyped dict-only handoffs at stage boundaries (NFR-1).
- **Orchestration**: A single entry point (e.g., pipeline runner or CLI) shall enforce stage order and pass outputs between stages. Stages do not call each other directly except through the orchestrator or an explicit router (e.g., ExtractionRouter).

### 3.2 Agentic & Strategy Pattern

- **Agents**: Each pipeline “stage” is implemented as an **agent** (Triage Agent, Extraction Router, Chunking Engine, PageIndex Builder, Query Agent). Agents are stateless per run; state is persisted via artifacts (`.refinery/profiles/`, `.refinery/extraction_ledger.jsonl`, `.refinery/pageindex/`).
- **Extraction strategies**: The Extraction layer uses the **Strategy pattern**. A common interface (e.g., `BaseExtractor` or protocol) is implemented by `FastTextExtractor`, `LayoutExtractor`, and `VisionExtractor`. The `ExtractionRouter` selects and invokes the appropriate strategy based on `DocumentProfile` and confidence, with escalation (FR-2.5, FR-2.6).
- **Pluggability**: Domain hint classification (FR-1.4) and, where applicable, extraction strategies shall be pluggable (e.g., keyword-based vs VLM classifier) so implementations can be swapped without changing the pipeline contract.

### 3.3 Adapters for Normalization

- **Single canonical schema**: All extraction strategies produce an **ExtractedDocument** (internal Pydantic model). External tool outputs (MinerU, Docling, VLM) are normalized via **adapters** that map into this schema (FR-2.7).
- **Adapter placement**: Adapters live in `src/strategies/` or a dedicated `src/adapters/` (e.g., `DoclingDocumentAdapter`, `MinerUAdapter`). They depend on the internal `src/models/` schemas, not the reverse.

### 3.4 Configuration-Driven Behavior

- **Externalized rules**: Confidence thresholds, budget cap, chunking limits, and extraction rules are **externalized** in YAML (e.g., `rubric/extraction_rules.yaml`) so behavior can change without code changes (IR-2, NFR-3).
- **Config loading**: Use a single config loader (e.g., Pydantic Settings or a small config module) that reads env and YAML; inject config into agents/strategies rather than reading files inside them.

---

## 4. Tech Stack

### 4.1 Core (Mandatory)

| Concern | Technology | SRS / Notes |
|--------|------------|-------------|
| **Runtime** | Python 3.10+ | Assumptions, DC-2 |
| **Schemas & validation** | Pydantic v2 | DR-1, NFR-1 |
| **Project & deps** | pyproject.toml, locked deps | DC-2 |
| **PDF – Fast Text** | pdfplumber or pymupdf | FR-2.1 |
| **PDF – Layout** | MinerU or Docling | FR-2.3 |
| **Vision extraction** | VLM via OpenRouter (e.g., Gemini Flash, GPT-4o-mini) | FR-2.4, FR-2.9 |
| **Query agent** | LangGraph | FR-5.1 |
| **Vector store** | ChromaDB or FAISS (local, free-tier friendly) | FR-5.5 |
| **Structured query** | SQLite + FactTable extractor | FR-5.3 |
| **Config** | YAML (extraction/chunking rules), env (secrets) | IR-2, IR-3 |

### 4.2 Recommended / Optional

| Concern | Technology | Notes |
|--------|------------|--------|
| **Testing** | pytest, pytest-cov | DC-3 |
| **Linting/formatting** | Ruff | §2.2 |
| **LLM for summaries** | Fast, cheap model for PageIndex section summaries | FR-4.1 |
| **Embeddings** | Model compatible with chosen vector store (e.g., sentence-transformers) | For semantic_search |
| **Containerization** | Docker (Dockerfile recommended for final submission) | Challenge deliverables |

### 4.3 Out of Scope for Stack

- No specific cloud provider or PaaS required.
- No enterprise SSO or IAM.
- No real-time streaming ingestion.

---

## 5. API Design Patterns

Concrete signatures, schema field lists, and wire formats are defined in [api_contracts.md](api_contracts.md). This section states the patterns; the contracts document is the single source for implementable interfaces.

### 5.1 Agent Interfaces

- **Input/output**: Each agent exposes a single primary method (e.g., `run` or `process`) that accepts a Pydantic model or a small set of typed arguments and returns a Pydantic model or a list of models. Exact types and method names are specified in api_contracts.md.
- **Errors**: Use explicit exceptions (e.g., `ExtractionBudgetExceeded`, `ValidationError`) rather than generic `Exception`. Document raised exceptions in docstrings.
- **Idempotency**: Triage and extraction for a given document and config should be deterministic (NFR-4). Query and PageIndex traversal may be non-deterministic where LLM is involved; document this where applicable.

### 5.2 Schema Design

- **Models**: All cross-stage data (DocumentProfile, ExtractedDocument, LDU, PageIndex node, ProvenanceChain) are Pydantic models in `src/models/` (DR-1). Field-level contracts (required fields, types, and invariants) are documented in api_contracts.md.
- **Serialization**: Models must be JSON-serializable (`.model_dump()` / `.model_dump_json()`). Use Pydantic’s serialization for artifacts (profiles, pageindex, ledger entries).
- **Bounding box**: Standardize on a single representation (e.g., `(x0, top, x1, bottom)` in points or a small dict) and document it (DR-2). Use a type alias or a small Pydantic model (e.g., `BoundingBox`) for consistency.
- **Versioning**: Schema changes that break compatibility should be reflected in artifact file names or a `version` field in persisted JSON where useful.

### 5.3 Configuration API

- **Structure**: Use a single root config object (e.g., `RefineryConfig`) that holds extraction thresholds, budget cap, paths (e.g., `.refinery/`), and feature flags. Load from YAML + env.
- **Validation**: Validate config at startup; fail fast with clear errors if required keys or env vars are missing.
- **No magic defaults**: Defaults for thresholds and limits should live in config or in a single defaults module, not scattered across agents.

### 5.4 Logging & Ledgers

- **Structured logging**: Prefer structured fields (e.g., `doc_id`, `strategy`, `confidence`) for key events so logs can be queried.
- **Extraction ledger**: Append-only JSONL (`.refinery/extraction_ledger.jsonl`) with fields: `strategy_used`, `confidence_score`, `cost_estimate`, `processing_time` (FR-2.8). Each line is a single JSON object; use Pydantic to serialize ledger entries.
- **No PII in logs**: Avoid logging raw document content; log hashes or doc_id only where sufficient for debugging.

---

## 6. Project Layout

Layout shall align with SRS design constraints (DC-1) and support clear separation of models, agents, strategies, and configuration.

```
project_root/
├── pyproject.toml
├── README.md
├── .env.example
├── .gitignore
├── data/                    # Optional: corpus or symlink to data.zip contents
├── docs/
│   └── challenge_document.md
├── specs/
│   ├── _meta.md             # This document
│   ├── system_requirement_spec.md
│   ├── api_contracts.md     # Agent interfaces, schemas, config & ledger contracts
│   ├── system_architecture.md
│   └── functional_requirements.md
├── rubric/
│   └── extraction_rules.yaml
├── src/
│   ├── __init__.py
│   ├── models/              # Pydantic schemas (DR-1)
│   │   ├── __init__.py
│   │   ├── document_profile.py
│   │   ├── extracted_document.py
│   │   ├── ldu.py
│   │   ├── pageindex.py
│   │   └── provenance.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── triage.py
│   │   ├── extractor.py     # ExtractionRouter
│   │   ├── chunker.py
│   │   ├── indexer.py       # PageIndex builder
│   │   └── query_agent.py
│   ├── strategies/         # Extraction strategies + adapters
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── fast_text.py
│   │   ├── layout.py
│   │   └── vision.py
│   └── config.py            # Config loading and RefineryConfig
├── .refinery/               # Pipeline artifacts (gitignored or committed per policy)
│   ├── profiles/
│   ├── pageindex/
│   └── extraction_ledger.jsonl
└── tests/
    ├── conftest.py
    ├── test_triage.py
    ├── test_extraction_confidence.py
    └── ...
```

- **DOMAIN_NOTES.md**: Can live at project root or under `docs/`; referenced in SRS and _meta for extraction decision tree and failure modes.

---

## 7. Error Handling & Resilience

- **Escalation**: On low confidence, the extraction layer escalates to the next strategy automatically; do not raise to the user unless all strategies are exhausted or budget is exceeded (FR-2.5, BR-2).
- **Budget guard**: When the per-document vision budget is exceeded, stop VLM calls for that document, log the event, and return partial results or a clear status (FR-2.9, BR-3).
- **Validation**: Use Pydantic validators for invariants (e.g., `page_start <= page_end` in PageIndex). Validate at boundaries (e.g., ChunkValidator before emitting LDUs per FR-3.3).
- **File I/O**: Handle missing files and permission errors explicitly; surface document path and stage in error messages for debugging.

---

## 8. Observability & Reproducibility

- **Ledger**: Every extraction run is logged with strategy, confidence, cost, and timing (FR-2.8, NFR-2).
- **Provenance**: Every query answer includes a ProvenanceChain (FR-5.2). Preserve document name, page number, bbox, and content_hash for audit.
- **Reproducibility**: Same document + same config → same DocumentProfile and same strategy selection (NFR-4). Seed any RNG if used; document any non-determinism in LLM-based steps.

---

## 9. What to Add in System Architecture

The **system_architecture.md** document (to be created) shall describe:

- **Component diagram**: Triage, ExtractionRouter, Extractors, ChunkingEngine, PageIndex Builder, Query Agent, Vector Store, SQLite.
- **Data flow diagram**: Input document → DocumentProfile → ExtractedDocument → LDUs → PageIndex + vector store + fact table; Query Agent using pageindex_navigate, semantic_search, structured_query.
- **Strategy selection and escalation**: Decision flow from DocumentProfile to strategy choice and escalation path.
- **Deployment view**: Optional; if present, align with Docker and local execution assumed in SRS.

All architectural decisions must stay within the technical standards and patterns defined in this _meta.md, the contracts in api_contracts.md, and must satisfy the SRS.

---

*End of Meta: Technical Standards & Implementation Governance*
