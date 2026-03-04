"""
Phase 0: Run Docling on one sample PDF and export markdown for comparison.
Install deps with: uv sync
Usage: uv run python phase0_docling_run.py [path_to_pdf]
"""
from __future__ import annotations

import sys
from pathlib import Path

def main() -> None:
    try:
        from docling.document_converter import DocumentConverter
    except ImportError:
        print("Docling not installed. Run: uv sync")
        sys.exit(1)

    root = Path(__file__).resolve().parent.parent
    data_dir = root / "data" / "data"
    default_pdf = data_dir / "tax_expenditure_ethiopia_2021_22.pdf"
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_pdf

    if not pdf_path.exists():
        print(f"Not found: {pdf_path}")
        sys.exit(1)

    out_dir = root / "docs" / "phase0_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / f"{pdf_path.stem}_docling.md"

    converter = DocumentConverter()
    result = converter.convert(str(pdf_path))
    md = result.document.export_to_markdown()
    out_md.write_text(md, encoding="utf-8")
    print(f"Docling output written to {out_md} ({len(md)} chars)")

if __name__ == "__main__":
    main()
