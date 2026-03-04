# Document Intelligence Refinery

Production-grade agentic pipeline that ingests unstructured documents and emits structured, queryable, spatially-indexed knowledge with full provenance.

## Setup (uv)

This project uses [uv](https://docs.astral.sh/uv/) for package management. From the project root:

```bash
# Create .venv and install dependencies
uv sync

# Run scripts (examples below)
uv run python scripts/phase0_analyze.py
uv run python scripts/phase1_triage_corpus.py
uv run python scripts/phase2_extract_corpus.py
uv run pytest tests/ -v
```

To add a dependency:

```bash
uv add <package>
uv add --dev <package>   # dev only
```

## Project structure

```
document-intelligence-refinery/
├── specs/                    # Authority: SRS, architecture, API contracts
│   ├── system_requirement_spec.md
│   ├── system_architecture.md
│   ├── api_contracts.md
│   ├── functional_requirements.md
│   └── _meta.md
├── docs/
│   ├── DOMAIN_NOTES.md       # Extraction decision tree, failure modes, pipeline
│   ├── IMPLEMENTATION_PLAN.md
│   └── INTERIM_REPORT.md
├── rubric/
│   └── extraction_rules.yaml # Triage & extraction thresholds; domain keywords (IR-2)
├── data/
│   └── data/                 # Corpus PDFs
├── .refinery/                # Artifacts (created by pipeline)
│   ├── profiles/             # DocumentProfile per doc (Phase 1)
│   └── extraction_ledger.jsonl
├── src/
│   ├── config.py             # RefineryConfig, ExtractionConfig, load_config
│   ├── exceptions.py         # ExtractionBudgetExceeded
│   ├── models/
│   │   ├── document_profile.py   # BoundingBox, DocumentProfile
│   │   └── extracted_document.py # TextBlock, Table, Figure, ReadingOrderItem,
│   │                              # ExtractedDocument, ExtractionResult, LedgerEntry
│   ├── agents/
│   │   ├── triage.py         # TriageAgent (run → DocumentProfile, persist)
│   │   └── extractor.py      # ExtractionRouter (run → ExtractedDocument, ledger)
│   └── strategies/
│       ├── base.py           # ExtractorProtocol
│       ├── fast_text.py      # FastTextExtractor (pdfplumber)
│       ├── layout.py         # LayoutExtractor (Docling adapter)
│       └── vision.py         # VisionExtractor (stub; OpenRouter placeholder)
├── scripts/
│   ├── phase0_analyze.py     # pdfplumber analysis on corpus
│   ├── phase0_docling_run.py # Docling sample run
│   ├── phase0_report_data.py # Report metrics for docs
│   ├── phase1_triage_corpus.py # Triage all PDFs → .refinery/profiles/
│   └── phase2_extract_corpus.py # Extract all profiled docs → ledger
└── tests/
    ├── conftest.py           # project_root, data_dir, sample PDFs, temp_refinery_dir
    ├── test_triage.py        # Triage classification & persistence
    └── test_extraction.py    # Router, confidence, escalation, ledger
```

## Implementation status

| Phase | Description | Status |
|-------|-------------|--------|
| **0** | Domain onboarding (DOMAIN_NOTES, decision tree, pipeline) | Done |
| **1** | Triage Agent & Document Profiling (DocumentProfile, `.refinery/profiles/`) | Done |
| **2** | Multi-Strategy Extraction (Fast Text, Layout, Vision stub, router, ledger) | Done |
| **3** | Semantic Chunking & PageIndex (LDU, ChunkingEngine, PageIndex, vector store) | Not started |
| **4** | Query Agent & Provenance (tools, ProvenanceChain, Audit Mode, FactTable) | Not started |

**Pipeline (Phases 0–2):** Triage classifies each PDF (origin type, layout complexity, domain, estimated cost) and writes a profile; the ExtractionRouter selects strategy (A → B → C) from the profile, runs the extractor, escalates on low confidence, and appends every attempt to `extraction_ledger.jsonl`. Strategy A (Fast Text) uses pdfplumber; B uses Docling when available; C (Vision) is a stub.

Details and task lists: [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## Configuration (no code change for thresholds or domain keywords)

All triage thresholds and **domain keyword lists** are in **`rubric/extraction_rules.yaml`**. To add or change which filenames map to which domain (financial, legal, technical, medical, general), edit the `triage.domain_keywords` section only; no code changes required. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the full "add a new domain by editing config only" workflow and threshold reference.

## Quick commands

| Goal | Command |
|------|--------|
| Triage all PDFs under `data/` | `uv run python scripts/phase1_triage_corpus.py` |
| Extract all profiled docs (run after triage) | `uv run python scripts/phase2_extract_corpus.py` |
| Run tests | `uv run pytest tests/ -v` |
| Phase 0: analyze sample PDFs | `uv run python scripts/phase0_analyze.py` |
| Phase 0: Docling on one PDF | `uv run python scripts/phase0_docling_run.py [path/to/doc.pdf]` |
