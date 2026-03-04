"""
Run Triage + ExtractionRouter on all PDFs with profiles under .refinery/profiles/.
Writes .refinery/extraction_ledger.jsonl. Use for Phase 2 deliverable.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.extractor import ExtractionRouter
from src.agents.triage import TriageAgent
from src.config import load_config
from src.models.document_profile import DocumentProfile


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    config = load_config(refinery_dir=root / ".refinery", project_root=root)
    profiles_dir = config.get_profiles_dir()
    if not profiles_dir.exists():
        print("No .refinery/profiles/ found. Run phase1_triage_corpus.py first.")
        return

    profile_files = sorted(profiles_dir.glob("*.json"))
    if not profile_files:
        print("No profile JSONs in .refinery/profiles/. Run phase1_triage_corpus.py first.")
        return

    data_dir = root / "data" / "data"
    if not data_dir.exists():
        data_dir = root / "data"

    triage = TriageAgent(config=config)
    router = ExtractionRouter(config=config)

    pdfs_by_stem = {p.stem: p for p in data_dir.rglob("*.pdf") if p.exists()}
    for pf in profile_files:
        doc_id = pf.stem
        profile = DocumentProfile.model_validate_json(pf.read_text(encoding="utf-8"))
        pdf_path = pdfs_by_stem.get(doc_id)
        if not pdf_path:
            print(f"  {doc_id}: no PDF found, skip")
            continue
        try:
            doc = router.run(profile, pdf_path, doc_id, config=config)
            print(f"  {doc_id}: extracted {len(doc.text_blocks)} text blocks")
        except Exception as e:
            print(f"  {doc_id}: ERROR {e}")

    ledger_path = config.get_ledger_path()
    if ledger_path.exists():
        count = sum(1 for _ in ledger_path.open(encoding="utf-8"))
        print(f"Ledger: {ledger_path} ({count} entries).")


if __name__ == "__main__":
    main()
