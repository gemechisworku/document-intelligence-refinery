"""
Phase 4: Populate FactTable, initialize QueryAgent, and run 12 example Q&A.
Usage:
    uv run python scripts/phase4_query_agent.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

# Ensure project root on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.agents.extractor import ExtractionRouter
from src.agents.fact_extractor import FactTableExtractor
from src.agents.query_agent import QueryAgent
from src.config import load_config
from src.models.document_profile import DocumentProfile


def main() -> None:
    config = load_config(project_root=project_root)
    profiles_dir = config.get_profiles_dir()

    if not profiles_dir.exists():
        print(f"No profiles directory found at {profiles_dir}. Run phase1 first.")
        return

    profile_files = sorted(profiles_dir.glob("*.json"))
    data_dir = project_root / "data" / "data"
    
    # 1. Populate Fact Tables
    print("--------------------------------------------------")
    print("Step 1: Populating Fact Tables from Extracted Docs")
    print("--------------------------------------------------")
    router = ExtractionRouter(config=config)
    fact_extractor = FactTableExtractor(config=config)
    
    # Actually extracting every doc is slow unless it's cached or fast_text
    # We'll run it and count facts
    total_facts = 0
    for pf in profile_files:
        doc_id = pf.stem
        try:
            profile_data = json.loads(pf.read_text(encoding="utf-8"))
            profile = DocumentProfile.model_validate(profile_data)
            
            # FactTableExtractor is most useful on financial documents with tables
            if profile.domain_hint != "financial" and "audit" not in doc_id.lower() and "tax" not in doc_id.lower():
                continue
                
            candidates = list(data_dir.glob(f"{doc_id}.*"))
            if candidates:
                doc_path = candidates[0]
                extracted = router.run(profile, doc_path, doc_id, config)
                count = fact_extractor.run(extracted, doc_id, config)
                total_facts += count
                print(f"  ✓ {doc_id} -> {count} facts inserted.")
            else:
                print(f"  ⚠ {doc_id} -> PDF missing.")
        except Exception as e:
            print(f"  ✗ {doc_id} -> Fact table extraction error: {e}")
            
    print(f"\nTotal facts successfully parsed: {total_facts}\n")

    # 2. Query Agent Example Q&A
    print("--------------------------------------------------")
    print("Step 2: Initialize LangGraph QueryAgent & Run Q&A")
    print("--------------------------------------------------")
    
    # For vectors, we will just pass None to QueryAgent for this demo 
    # unless chroma is up. The semantic_search tool handles None gracefully.
    try:
        import chromadb  # type: ignore
        client = chromadb.Client()
        # In a real scenario we'd query the previously created collection.
        # But for this demo, we'll try to find it.
        try:
            vs = client.get_collection(name="refinery_ldus")
        except Exception:
            vs = None
    except ImportError:
        vs = None
        
    agent = QueryAgent(config=config, vector_store=vs)
    
    # 12 Sample questions spanning different categories
    questions = [
        "What is the total revenue for the latest fiscal year?",
        "Are there any compliance audits reported?",
        "What was the focus of the performance survey?",
        "List the key findings from the technical assessment.",
        "Did the company report a legal dispute?",
        "What is the summary of the tax expenditure in Ethiopia?",
        "Who authored the medical guidelines?",
        "What is the layout of the financial tables?",
        "Are there any cross-references to Figure 1?",
        "What is the profit margin stated in the Audit Report 2023?",
        "Which regulation dictates the compliance procedures?",
        "What is the largest expenditure item listed?",
    ]
    
    claims_to_audit = [
        "The company reported over $50M in revenue.",
        "The tax expenditure in Ethiopia was reduced by 10%.",
        "The FTA performance survey has negative findings."
    ]

    for i, q in enumerate(questions, 1):
        print(f"Q{i}: {q}")
        res = agent.run(q)
        print(f"A : {res.answer[:200]}{'...' if len(res.answer) > 200 else ''}")
        # Print provenance
        if res.provenance_chain and res.provenance_chain.citations:
            sources = [c.document_name for c in res.provenance_chain.citations]
            print(f"    Sources: {sources}")
        print()
        
    print("--------------------------------------------------")
    print("Step 3: Audit Mode (verify_claim)")
    print("--------------------------------------------------")
    for cp in claims_to_audit:
        print(f"Claim: '{cp}'")
        audit = agent.verify_claim(cp)
        status = "VERIFIED" if audit.verified else "UNVERIFIABLE/REFUTED"
        print(f"Result: {status} => {audit.message}")
        print()

    print("Phase 4 Complete!")

if __name__ == "__main__":
    main()
