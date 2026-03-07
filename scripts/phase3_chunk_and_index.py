"""
Phase 3: Run ChunkingEngine + PageIndex Builder on all extracted documents.
Reads profiles from .refinery/profiles/, runs extraction, then chunks and indexes.

Usage:
    uv run python scripts/phase3_chunk_and_index.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.agents.chunker import ChunkingEngine
from src.agents.extractor import ExtractionRouter
from src.agents.indexer import PageIndexBuilder
from src.config import load_config
from src.models.document_profile import DocumentProfile


def main() -> None:
    config = load_config(project_root=project_root)
    profiles_dir = config.get_profiles_dir()

    if not profiles_dir.exists():
        print(f"No profiles directory found at {profiles_dir}. Run phase1 first.")
        return

    profile_files = sorted(profiles_dir.glob("*.json"))
    if not profile_files:
        print("No profile files found. Run phase1_triage_corpus.py first.")
        return

    data_dir = project_root / "data" / "data"
    if not data_dir.exists():
        print(f"Data directory not found at {data_dir}")
        return

    # Initialize agents
    router = ExtractionRouter(config=config)
    chunker = ChunkingEngine(config=config)
    indexer = PageIndexBuilder(config=config)

    total = len(profile_files)
    success = 0
    errors = 0

    for idx, pf in enumerate(profile_files, 1):
        doc_id = pf.stem
        print(f"\n[{idx}/{total}] Processing: {doc_id}")

        try:
            # Load profile
            profile_data = json.loads(pf.read_text(encoding="utf-8"))
            profile = DocumentProfile.model_validate(profile_data)

            # Find document
            doc_path = data_dir / f"{doc_id}.pdf"
            if not doc_path.exists():
                # Try other extensions or exact name
                candidates = list(data_dir.glob(f"{doc_id}.*"))
                if candidates:
                    doc_path = candidates[0]
                else:
                    print(f"  ⚠ Document not found: {doc_id}")
                    errors += 1
                    continue

            # Check if pageindex already exists
            pi_path = config.get_pageindex_path(doc_id)
            if pi_path.exists():
                print(f"  ✓ PageIndex already exists, skipping.")
                success += 1
                continue

            # Extract
            print(f"  → Extracting...")
            extracted = router.run(profile, doc_path, doc_id, config)

            if not extracted.text_blocks and not extracted.tables and not extracted.figures:
                print(f"  ⚠ Empty extraction, skipping chunking/indexing.")
                errors += 1
                continue

            # Chunk
            print(f"  → Chunking...")
            ldus = chunker.run(extracted, doc_id, config)
            print(f"    {len(ldus)} LDUs generated")

            # Build PageIndex
            print(f"  → Building PageIndex...")
            root = indexer.run(extracted, doc_id, config)
            child_count = len(root.child_sections)
            print(f"    PageIndex root: {root.title} ({child_count} children, "
                  f"pages {root.page_start}–{root.page_end})")

            success += 1
            print(f"  ✓ Done")

        except KeyboardInterrupt:
            print("\nInterrupted by user.")
            break
        except Exception as e:
            print(f"  ✗ Error: {e}")
            errors += 1

    print(f"\n{'='*60}")
    print(f"Phase 3 complete: {success}/{total} succeeded, {errors} errors")
    print(f"PageIndex artifacts: {config.get_pageindex_dir()}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
