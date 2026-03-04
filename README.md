# Document Intelligence Refinery

Production-grade agentic pipeline that ingests unstructured documents and emits structured, queryable, spatially-indexed knowledge with full provenance.

## Setup (uv)

This project uses [uv](https://docs.astral.sh/uv/) for package management. Install uv, then from the project root:

```bash
# Create .venv and install locked dependencies
uv sync

# Run a script with project deps (e.g. Phase 0 analysis)
uv run python scripts/phase0_analyze.py
uv run python scripts/phase0_docling_run.py [path/to/doc.pdf]
```

To add a dependency and update the lockfile:

```bash
uv add <package>
# or for dev
uv add --dev <package>
```

## Project layout

- `specs/` — System requirement spec, architecture, api_contracts, _meta
- `docs/` — Challenge document, DOMAIN_NOTES.md, IMPLEMENTATION_PLAN.md
- `scripts/` — Phase 0 analysis scripts
- `data/data/` — Corpus PDFs (e.g. from data.zip)
- `src/` — Application code (to be added in Phase 1+)
- `rubric/` — extraction_rules.yaml (Phase 2+)