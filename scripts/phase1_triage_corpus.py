"""
Run Triage Agent on all PDFs under data/ and write .refinery/profiles/{doc_id}.json.
Use for Phase 1 deliverable: profiles for >=12 docs (min 3 per class A/B/C/D).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.triage import TriageAgent
from src.config import load_config


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    data_dir = root / "data" / "data"
    if not data_dir.exists():
        data_dir = root / "data"
    config = load_config(refinery_dir=root / ".refinery", project_root=root)
    config.get_profiles_dir().mkdir(parents=True, exist_ok=True)
    agent = TriageAgent(config=config)

    pdfs = sorted(data_dir.rglob("*.pdf"))
    if not pdfs:
        print("No PDFs found under data/ or data/data/. Place corpus there and re-run.")
        return

    print(f"Running triage on {len(pdfs)} PDF(s) under {data_dir}.")
    for path in pdfs:
        doc_id = path.stem
        try:
            profile = agent.run(path, doc_id)
            print(f"  {doc_id}: origin={profile.origin_type} cost={profile.estimated_extraction_cost}")
        except Exception as e:
            print(f"  {doc_id}: ERROR {e}")

    profiles_dir = config.get_profiles_dir()
    count = len(list(profiles_dir.glob("*.json")))
    print(f"Profiles written to {profiles_dir} ({count} total).")


if __name__ == "__main__":
    main()
