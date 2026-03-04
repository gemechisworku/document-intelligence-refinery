"""
Phase 0: Document science primer — pdfplumber analysis.
Analyzes character density, bbox distribution, image area ratio, and text presence
to inform extraction strategy decision tree (native_digital vs scanned vs mixed).
Output: printed summary and observations for DOMAIN_NOTES.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("Install deps with: uv sync", file=sys.stderr)
    sys.exit(1)


def analyze_pdf(path: Path, max_pages: int = 10) -> dict:
    """Analyze a PDF with pdfplumber: chars per page, image area, bbox stats."""
    results = {
        "path": str(path),
        "name": path.name,
        "pages_analyzed": 0,
        "total_chars": 0,
        "total_page_area_pt2": 0.0,
        "total_image_area_pt2": 0.0,
        "per_page": [],
        "has_text_stream": False,
        "chars_per_page_avg": 0.0,
        "image_area_ratio_avg": 0.0,
    }
    with pdfplumber.open(path) as pdf:
        results["num_pages"] = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            if i >= max_pages:
                break
            w = page.width
            h = page.height
            page_area = w * h
            results["total_page_area_pt2"] += page_area

            # Character count and bbox from chars
            chars = page.chars
            text = page.extract_text() or ""
            char_count = len(text.replace(" ", "").replace("\n", ""))  # non-whitespace
            # Also use raw char count from page.chars for accuracy
            raw_char_count = len(chars)
            if raw_char_count > 0:
                results["has_text_stream"] = True

            # Image area: sum of image bounding boxes (crop/figures)
            imgs = page.images
            img_area = 0.0
            for im in imgs:
                x0, top, x1, bottom = im.get("x0", 0), im.get("top", 0), im.get("x1", 0), im.get("bottom", 0)
                img_area += (x1 - x0) * (bottom - top)
            results["total_image_area_pt2"] += img_area

            # Bbox distribution: from chars
            bbox_count = len(chars)
            results["total_chars"] += max(char_count, raw_char_count)

            per_page = {
                "page": i + 1,
                "char_count": max(char_count, raw_char_count),
                "page_area_pt2": page_area,
                "image_area_pt2": img_area,
                "image_ratio": img_area / page_area if page_area else 0,
                "num_char_bboxes": bbox_count,
            }
            results["per_page"].append(per_page)
            results["pages_analyzed"] += 1

        if results["pages_analyzed"]:
            results["chars_per_page_avg"] = results["total_chars"] / results["pages_analyzed"]
            results["image_area_ratio_avg"] = (
                results["total_image_area_pt2"] / results["total_page_area_pt2"]
                if results["total_page_area_pt2"] else 0
            )
    return results


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    data_dir = root / "data" / "data"
    if not data_dir.is_dir():
        print(f"Data dir not found: {data_dir}", file=sys.stderr)
        sys.exit(1)

    # Representative samples: challenge classes A–D + one clearly scanned
    samples = [
        "CBE ANNUAL REPORT 2023-24.pdf",   # Class A: native digital annual report
        "Audit Report - 2023.pdf",          # Class B: scanned government/legal
        "fta_performance_survey_final_report_2022.pdf",  # Class C: mixed technical
        "tax_expenditure_ethiopia_2021_22.pdf",          # Class D: table-heavy
        "2018_Audited_Financial_Statement_Report.pdf",  # Likely mixed/table
    ]
    pdfs = []
    for name in samples:
        p = data_dir / name
        if p.exists():
            pdfs.append(p)
        else:
            # Fallback: any first few PDFs
            pass
    if not pdfs:
        pdfs = list(data_dir.glob("*.pdf"))[:5]

    print("=" * 60)
    print("Phase 0: pdfplumber analysis (character density, image ratio, bbox)")
    print("=" * 60)

    all_observations = []
    for path in pdfs:
        r = analyze_pdf(path, max_pages=8)
        print(f"\n--- {r['name']} ---")
        print(f"  Pages (total): {r['num_pages']}  (analyzed first {r['pages_analyzed']})")
        print(f"  Has text stream (native text): {r['has_text_stream']}")
        print(f"  Total chars (analyzed pages): {r['total_chars']}")
        print(f"  Chars/page (avg): {r['chars_per_page_avg']:.0f}")
        print(f"  Image area ratio (avg): {r['image_area_ratio_avg']:.2%}")

        # Heuristic: likely scanned if very few chars and/or high image ratio
        likely_scanned = not r["has_text_stream"] or (
            r["chars_per_page_avg"] < 100 and r["image_area_ratio_avg"] > 0.3
        )
        likely_native = r["has_text_stream"] and r["chars_per_page_avg"] > 500 and r["image_area_ratio_avg"] < 0.5
        print(f"  Heuristic: likely_scanned={likely_scanned}, likely_native_digital={likely_native}")

        for pp in r["per_page"][:3]:
            print(f"    Page {pp['page']}: chars={pp['char_count']}, image_ratio={pp['image_ratio']:.2%}")

        all_observations.append({
            "name": r["name"],
            "has_text_stream": r["has_text_stream"],
            "chars_per_page_avg": r["chars_per_page_avg"],
            "image_area_ratio_avg": r["image_area_ratio_avg"],
            "likely_scanned": likely_scanned,
            "likely_native": likely_native,
        })

    print("\n" + "=" * 60)
    print("Summary for DOMAIN_NOTES.md")
    print("=" * 60)
    for obs in all_observations:
        origin = "scanned_image" if obs["likely_scanned"] else ("native_digital" if obs["likely_native"] else "mixed")
        print(f"  {obs['name'][:50]:50} -> {origin} (chars/pg~{obs['chars_per_page_avg']:.0f}, img_ratio~{obs['image_area_ratio_avg']:.2%})")


if __name__ == "__main__":
    main()
