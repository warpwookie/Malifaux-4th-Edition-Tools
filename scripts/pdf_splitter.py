#!/usr/bin/env python3
"""
pdf_splitter.py â€” Extract front/back card images from M4E stat card PDFs.

Each PDF contains 2 pages: front (page 0) and back (page 1).
Crew cards are typically 1 page.
Outputs PNG images at 250 DPI for optimal vision model parsing.

Usage:
    python pdf_splitter.py input.pdf --output-dir ./images/
    python pdf_splitter.py ./pdf_folder/ --output-dir ./images/  # batch mode
"""
import argparse
import os
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: PyMuPDF required. Install: pip install PyMuPDF")
    sys.exit(1)


DEFAULT_DPI = 250
SUPPORTED_EXTENSIONS = {".pdf"}


def extract_card_images(pdf_path: str, output_dir: str, dpi: int = DEFAULT_DPI) -> list[dict]:
    """
    Extract pages from a PDF as PNG images.
    
    Returns list of dicts with extraction metadata:
    [{"pdf": "...", "page": 0, "side": "front", "image_path": "..."}, ...]
    """
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    stem = pdf_path.stem  # e.g., "M4E_Stat_BigHat_Bayou_Gremlin_A"
    
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        return [{"pdf": str(pdf_path), "error": str(e)}]
    
    results = []
    page_count = len(doc)
    
    for i in range(page_count):
        if page_count == 1:
            # Single page = crew card or single-sided
            side = "single"
        elif page_count == 2:
            side = "front" if i == 0 else "back"
        else:
            side = f"page_{i}"
        
        pix = doc[i].get_pixmap(dpi=dpi)
        image_filename = f"{stem}_{side}.png"
        image_path = output_dir / image_filename
        pix.save(str(image_path))
        
        results.append({
            "pdf": str(pdf_path),
            "pdf_stem": stem,
            "page": i,
            "page_count": page_count,
            "side": side,
            "image_path": str(image_path),
            "card_type": classify_card_type(stem),
        })
    
    doc.close()
    return results


def classify_card_type(stem: str) -> str:
    """Classify card type from filename convention."""
    stem_lower = stem.lower()
    if "_crew_" in stem_lower:
        return "crew_card"
    elif "_stat_" in stem_lower:
        return "stat_card"
    elif "_upgrade_" in stem_lower:
        return "upgrade_card"
    else:
        return "unknown"


def detect_alt_art_group(stem: str) -> tuple[str, str]:
    """
    Detect if a filename is an alt-art variant.
    Returns (base_name, variant_suffix).
    e.g., "M4E_Stat_BigHat_Bayou_Gremlin_A" -> ("M4E_Stat_BigHat_Bayou_Gremlin", "A")
    """
    # Check if last segment after final underscore is a single letter A-Z
    parts = stem.rsplit("_", 1)
    if len(parts) == 2 and len(parts[1]) == 1 and parts[1].isalpha() and parts[1].isupper():
        return parts[0], parts[1]
    return stem, ""


def batch_extract(input_dir: str, output_dir: str, dpi: int = DEFAULT_DPI) -> list[dict]:
    """Process all PDFs in a directory."""
    input_dir = Path(input_dir)
    all_results = []
    
    pdf_files = sorted(input_dir.glob("*.pdf")) + sorted(input_dir.glob("**/*.pdf"))
    # Deduplicate
    seen = set()
    unique_pdfs = []
    for p in pdf_files:
        if str(p) not in seen:
            seen.add(str(p))
            unique_pdfs.append(p)
    
    print(f"Found {len(unique_pdfs)} PDFs in {input_dir}")
    
    # Group by alt-art to identify which need parsing vs. skipping
    alt_art_groups = {}
    for pdf in unique_pdfs:
        base, variant = detect_alt_art_group(pdf.stem)
        alt_art_groups.setdefault(base, []).append((pdf, variant))
    
    print(f"Unique card groups (after alt-art dedup): {len(alt_art_groups)}")
    
    for base, variants in sorted(alt_art_groups.items()):
        # Only process the first variant (A or no suffix); skip B, C, etc.
        primary = variants[0]
        pdf, variant = primary
        
        results = extract_card_images(str(pdf), output_dir, dpi)
        for r in results:
            r["alt_art_group"] = base
            r["alt_art_variant"] = variant
            r["alt_art_count"] = len(variants)
            r["skipped_variants"] = [v[1] for v in variants[1:]]
        
        all_results.extend(results)
        
        if len(variants) > 1:
            skipped = [v[1] for v in variants[1:]]
            print(f"  {base}: parsed variant {variant or 'base'}, skipped {skipped}")
    
    return all_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract M4E card images from PDFs")
    parser.add_argument("input", help="PDF file or directory of PDFs")
    parser.add_argument("--output-dir", "-o", default="./extracted_images", help="Output directory")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="Extraction DPI")
    parser.add_argument("--json-manifest", "-j", help="Write extraction manifest to JSON file")
    args = parser.parse_args()
    
    input_path = Path(args.input)
    
    if input_path.is_file():
        results = extract_card_images(str(input_path), args.output_dir, args.dpi)
    elif input_path.is_dir():
        results = batch_extract(str(input_path), args.output_dir, args.dpi)
    else:
        print(f"ERROR: {args.input} not found")
        sys.exit(1)
    
    # Summary
    errors = [r for r in results if "error" in r]
    success = [r for r in results if "error" not in r]
    print(f"\nExtracted: {len(success)} images from {len(set(r.get('pdf','') for r in success))} PDFs")
    if errors:
        print(f"Errors: {len(errors)}")
        for e in errors:
            print(f"  {e['pdf']}: {e['error']}")
    
    if args.json_manifest:
        import json
        with open(args.json_manifest, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Manifest written to {args.json_manifest}")
