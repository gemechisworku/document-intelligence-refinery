"""
Phase 0: Generate structured analysis data for the interim report.
Outputs JSON with per-document metrics for all 4 classes (A/B/C/D) and
page-level variation. Run: uv run python scripts/phase0_report_data.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("Install deps with: uv sync", file=sys.stderr)
    sys.exit(1)


# Corpus mapping: challenge document classes with named files
CLASS_A = "native financial (annual report)"
CLASS_B = "scanned legal/government"
CLASS_C = "mixed assessment"
CLASS_D = "table-heavy fiscal"

CORPUS = [
    {"file": "CBE ANNUAL REPORT 2023-24.pdf", "class": "A", "class_desc": CLASS_A},
    {"file": "Audit Report - 2023.pdf", "class": "B", "class_desc": CLASS_B},
    {"file": "fta_performance_survey_final_report_2022.pdf", "class": "C", "class_desc": CLASS_C},
    {"file": "tax_expenditure_ethiopia_2021_22.pdf", "class": "D", "class_desc": CLASS_D},
    {"file": "2018_Audited_Financial_Statement_Report.pdf", "class": "B", "class_desc": CLASS_B},
    {"file": "Annual_Report_JUNE-2023.pdf", "class": "A", "class_desc": CLASS_A},
]


def analyze_pdf(path: Path, max_pages: int = 12) -> dict:
    with pdfplumber.open(path) as pdf:
        num_pages = len(pdf.pages)
        total_chars = 0
        total_page_area = 0.0
        total_image_area = 0.0
        has_text_stream = False
        per_page = []
        for i, page in enumerate(pdf.pages):
            if i >= max_pages:
                break
            w, h = page.width, page.height
            page_area = w * h
            total_page_area += page_area
            text = page.extract_text() or ""
            char_count = len(text.replace(" ", "").replace("\n", ""))
            raw_char_count = len(page.chars)
            if raw_char_count > 0:
                has_text_stream = True
            char_count = max(char_count, raw_char_count)
            total_chars += char_count
            img_area = 0.0
            for im in page.images:
                x0, top, x1, bottom = im.get("x0", 0), im.get("top", 0), im.get("x1", 0), im.get("bottom", 0)
                img_area += (x1 - x0) * (bottom - top)
            total_image_area += img_area
            per_page.append({
                "page": i + 1,
                "char_count": char_count,
                "image_ratio": round(img_area / page_area if page_area else 0, 4),
            })
        pages_analyzed = len(per_page)
        chars_per_page_avg = total_chars / pages_analyzed if pages_analyzed else 0
        image_ratio_avg = total_image_area / total_page_area if total_page_area else 0
        likely_scanned = not has_text_stream or (chars_per_page_avg < 100 and image_ratio_avg > 0.3)
        likely_native = has_text_stream and chars_per_page_avg > 500 and image_ratio_avg < 0.5
        origin = "scanned_image" if likely_scanned else ("native_digital" if likely_native else "mixed")
        return {
            "name": path.name,
            "num_pages": num_pages,
            "pages_analyzed": pages_analyzed,
            "has_text_stream": has_text_stream,
            "total_chars_analyzed": total_chars,
            "chars_per_page_avg": round(chars_per_page_avg, 1),
            "image_area_ratio_avg": round(image_ratio_avg, 4),
            "origin_type_heuristic": origin,
            "per_page_variation": per_page,
            "page_level_note": "Document-level and page-level variation observed" if max(p.get("char_count", 0) for p in per_page) - min(p.get("char_count", 0) for p in per_page) > 500 else "Moderate page-level variation",
        }


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    data_dir = root / "data" / "data"
    out_path = root / "docs" / "phase0_report_data.json"
    if not data_dir.is_dir():
        print(f"Data dir not found: {data_dir}", file=sys.stderr)
        sys.exit(1)

    results = {"documents": [], "summary_by_class": {}}
    for item in CORPUS:
        path = data_dir / item["file"]
        if not path.exists():
            continue
        r = analyze_pdf(path, max_pages=12)
        r["class"] = item["class"]
        r["class_desc"] = item["class_desc"]
        results["documents"].append(r)
        c = item["class"]
        if c not in results["summary_by_class"]:
            results["summary_by_class"][c] = []
        results["summary_by_class"][c].append(r["name"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Written {out_path}", file=sys.stderr)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
