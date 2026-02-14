#!/usr/bin/env python3
"""
pipeline.py â€” End-to-end M4E card parsing pipeline.

Orchestrates: PDF splitting â†’ Vision extraction â†’ JSON merging â†’ 
              Validation â†’ Database loading â†’ Audit logging

Usage:
    # Process a single PDF
    python pipeline.py single card.pdf --db m4e.db

    # Process all PDFs in a directory
    python pipeline.py batch ./pdfs/ --db m4e.db

    # Dry run (extract + validate but don't load to DB)
    python pipeline.py batch ./pdfs/ --db m4e.db --dry-run

    # Process only, skip existing models in DB
    python pipeline.py batch ./pdfs/ --db m4e.db --skip-existing

Requires: ANTHROPIC_API_KEY environment variable
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add parent to path so we can import sibling modules
sys.path.insert(0, str(Path(__file__).parent))

from pdf_splitter import extract_card_images, batch_extract, classify_card_type
from card_extractor import extract_stat_card, extract_crew_card
from merger import merge_stat_card
from validator import validate_card
from db_loader import init_db, load_stat_card, load_crew_card, log_parse

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic SDK required. Install: pip install anthropic")
    sys.exit(1)


class PipelineStats:
    """Track pipeline execution statistics."""
    def __init__(self):
        self.total_pdfs = 0
        self.extracted = 0
        self.merged = 0
        self.validated_pass = 0
        self.validated_fail = 0
        self.validated_review = 0
        self.loaded = 0
        self.skipped = 0
        self.errors = []
        self.start_time = time.time()
    
    def summary(self) -> str:
        elapsed = time.time() - self.start_time
        lines = [
            "=" * 60,
            "PIPELINE SUMMARY",
            "=" * 60,
            f"PDFs processed:    {self.total_pdfs}",
            f"Images extracted:   {self.extracted}",
            f"Cards merged:       {self.merged}",
            f"Validation passed:  {self.validated_pass}",
            f"Validation failed:  {self.validated_fail}",
            f"Needs review:       {self.validated_review}",
            f"Loaded to DB:       {self.loaded}",
            f"Skipped:            {self.skipped}",
            f"Errors:             {len(self.errors)}",
            f"Time elapsed:       {elapsed:.1f}s",
        ]
        if self.errors:
            lines.append("\nERRORS:")
            for e in self.errors:
                lines.append(f"  âœ— {e}")
        return "\n".join(lines)


def process_single_pdf(pdf_path: str, db_path: str, client: anthropic.Anthropic,
                       work_dir: str, dry_run: bool = False, replace: bool = False,
                       skip_existing: bool = False, source_faction: str = None) -> dict:
    """
    Process a single PDF through the full pipeline.
    
    Returns result dict with status and any issues.
    """
    pdf_path = Path(pdf_path)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    
    stem = pdf_path.stem
    card_type = classify_card_type(stem)
    
    print(f"\n{'â”€'*50}")
    print(f"Processing: {pdf_path.name} [{card_type}]")
    
    # Step 1: Extract images
    print("  Step 1: Extracting images...")
    images = extract_card_images(str(pdf_path), str(work_dir))
    
    if any("error" in img for img in images):
        error = next(img["error"] for img in images if "error" in img)
        return {"status": "error", "step": "extraction", "error": error}
    
    # Step 2: Vision extraction
    print("  Step 2: Vision model extraction...")
    
    if card_type in ("stat_card", "upgrade_card") and len(images) == 2:
        front_img = next((i for i in images if i["side"] == "front"), None)
        back_img = next((i for i in images if i["side"] == "back"), None)
        
        if not front_img or not back_img:
            return {"status": "error", "step": "extraction", 
                    "error": "Could not identify front/back pages"}
        
        extraction = extract_stat_card(client, front_img["image_path"], back_img["image_path"])
        
        if "error" in extraction:
            return {"status": "error", "step": "vision", "error": extraction["error"]}
        
        # Step 3: Merge
        print("  Step 3: Merging front + back...")
        merged = merge_stat_card(extraction["front"], extraction["back"], str(pdf_path))
        
    elif card_type == "crew_card":
        img = images[0]
        merged = extract_crew_card(client, img["image_path"])
        if "error" in merged:
            return {"status": "error", "step": "vision", "error": merged["error"]}
        merged["source_pdf"] = str(pdf_path)
    
    else:
        return {"status": "error", "step": "classification", 
                "error": f"Unexpected page count ({len(images)}) for {card_type}"}
    
    # Build factions list (detected + source faction for dual-faction support)
    detected_faction = merged.get("faction", "Unknown")
    factions = [detected_faction]
    if source_faction and source_faction != detected_faction:
        factions.append(source_faction)
    merged["factions"] = factions
    
    # Save merged JSON for traceability
    merged_path = work_dir / f"{stem}_merged.json"
    with open(merged_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    
    # Step 4: Validate
    print("  Step 4: Validating...")
    validation = validate_card(merged)
    print(f"    {validation.summary().split(chr(10))[0]}")  # First line only
    
    if not validation.passed:
        # Save for manual review
        failed_path = work_dir / f"{stem}_FAILED.json"
        with open(failed_path, "w", encoding="utf-8") as f:
            json.dump({"card": merged, "validation": validation.to_dict()}, f, indent=2)
        
        return {"status": "validation_failed", "validation": validation.to_dict(),
                "merged_path": str(merged_path)}
    
    # Step 5: Load to database
    if dry_run:
        print("  Step 5: [DRY RUN] Skipping database load")
        return {"status": "dry_run_pass", "validation": validation.to_dict()}
    
    print("  Step 5: Loading to database...")
    conn = init_db(db_path)
    
    try:
        if card_type == "crew_card":
            load_result = load_crew_card(conn, merged, replace)
        else:
            load_result = load_stat_card(conn, merged, replace)
        
        # Log the parse
        log_parse(conn, str(pdf_path), merged.get("name", "?"),
                  load_result["status"], validation.to_dict())
        
        conn.close()
        
        label = merged.get("name", "?")
        if merged.get("title"):
            label += f" ({merged['title']})"
        print(f"    {load_result['status'].upper()}: {label}")
        
        return {"status": load_result["status"], "validation": validation.to_dict(),
                "load_result": load_result}
    
    except Exception as e:
        conn.close()
        return {"status": "error", "step": "db_load", "error": str(e)}


def process_batch(input_dir: str, db_path: str, client: anthropic.Anthropic,
                  work_dir: str, dry_run: bool = False, replace: bool = False,
                  skip_existing: bool = False, delay: float = 1.0) -> PipelineStats:
    """
    Process all PDFs in a directory through the pipeline.
    """
    stats = PipelineStats()
    input_dir = Path(input_dir)
    
    # Collect all PDFs
    pdfs = sorted(input_dir.glob("**/*.pdf"))
    stats.total_pdfs = len(pdfs)
    print(f"Found {len(pdfs)} PDFs in {input_dir}")
    
    # If skip_existing, check what's already in DB
    existing_models = set()
    if skip_existing and os.path.exists(db_path):
        import sqlite3
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        try:
            c.execute("SELECT source_pdf FROM models WHERE source_pdf IS NOT NULL")
            existing_models = {row[0] for row in c.fetchall()}
        except:
            pass
        conn.close()
        print(f"Found {len(existing_models)} existing models in DB")
    
    for i, pdf in enumerate(pdfs):
        if skip_existing and str(pdf) in existing_models:
            print(f"  [{i+1}/{len(pdfs)}] SKIP (exists): {pdf.name}")
            stats.skipped += 1
            continue
        
        print(f"\n[{i+1}/{len(pdfs)}]", end="")
        
        try:
            result = process_single_pdf(
                str(pdf), db_path, client, work_dir, dry_run, replace, skip_existing
            )
            
            status = result.get("status", "unknown")
            if status in ("inserted", "updated", "dry_run_pass"):
                stats.extracted += 1
                stats.merged += 1
                stats.loaded += 1
                if result.get("validation", {}).get("needs_review"):
                    stats.validated_review += 1
                else:
                    stats.validated_pass += 1
            elif status == "skipped":
                stats.skipped += 1
            elif status == "validation_failed":
                stats.extracted += 1
                stats.merged += 1
                stats.validated_fail += 1
            else:
                stats.errors.append(f"{pdf.name}: {result.get('error', status)}")
        
        except Exception as e:
            stats.errors.append(f"{pdf.name}: {str(e)}")
        
        # Rate limiting delay
        if delay > 0 and i < len(pdfs) - 1:
            time.sleep(delay)
    
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="M4E Card Parsing Pipeline")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    
    # Single PDF mode
    single = subparsers.add_parser("single", help="Process a single PDF")
    single.add_argument("pdf", help="PDF file to process")
    
    # Batch mode
    batch = subparsers.add_parser("batch", help="Process all PDFs in a directory")
    batch.add_argument("dir", help="Directory containing PDFs")
    batch.add_argument("--delay", type=float, default=1.0, help="Delay between API calls (seconds)")
    
    # Common arguments
    for sub in [single, batch]:
        sub.add_argument("--db", required=True, help="Database path")
        sub.add_argument("--work-dir", default="./pipeline_work", help="Working directory for intermediates")
        sub.add_argument("--dry-run", action="store_true", help="Extract and validate only, don't load DB")
        sub.add_argument("--replace", action="store_true", help="Replace existing DB entries")
        sub.add_argument("--skip-existing", action="store_true", help="Skip PDFs already in DB")
        sub.add_argument("--model", default="claude-sonnet-4-5-20250929", help="Claude model to use")
    
    args = parser.parse_args()
    
    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY environment variable")
        sys.exit(1)
    
    # Override model in extractor module
    import card_extractor
    card_extractor.MODEL = args.model
    
    client = anthropic.Anthropic(api_key=api_key)
    
    if args.mode == "single":
        result = process_single_pdf(
            args.pdf, args.db, client, args.work_dir,
            args.dry_run, args.replace, args.skip_existing
        )
        print(f"\nResult: {result['status']}")
        
    elif args.mode == "batch":
        stats = process_batch(
            args.dir, args.db, client, args.work_dir,
            args.dry_run, args.replace, args.skip_existing, args.delay
        )
        print(f"\n{stats.summary()}")
    
    sys.exit(0)
