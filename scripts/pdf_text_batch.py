#!/usr/bin/env python3
"""
pdf_text_batch.py — Batch re-ingestion of M4E stat cards from PDF text layers.

Walks source_pdfs/ directories and processes all stat card PDFs through:
  pdf_text_extractor → merger → validator → db_loader

Usage:
    python scripts/pdf_text_batch.py --faction Guild
    python scripts/pdf_text_batch.py --all
    python scripts/pdf_text_batch.py --all --dry-run
    python scripts/pdf_text_batch.py --all --compare-only
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
DB_PATH = PROJECT_DIR / "db" / "m4e.db"
SOURCE_DIR = PROJECT_DIR / "source_pdfs"
WORK_DIR = PROJECT_DIR / "pipeline_work"

# Ensure project root is on sys.path
sys.path.insert(0, str(PROJECT_DIR))

from scripts.pdf_text_extractor import extract_stat_card_text
from scripts.merger import merge_stat_card
from scripts.validator import validate_card
from scripts.db_loader import load_stat_card, init_db


FACTIONS = [
    "Guild", "Arcanists", "Neverborn", "Bayou",
    "Outcasts", "Resurrectionists", "Ten Thunders", "Explorer's Society"
]


def discover_stat_pdfs(faction=None):
    """
    Walk source_pdfs/ to find all stat card PDFs.

    Only processes _A suffix (or no suffix) — skips _B, _C, _D alt-art variants.
    Returns list of (pdf_path, faction_name, keyword_name).
    """
    pdfs = []
    factions = [faction] if faction else FACTIONS

    for f_name in factions:
        faction_dir = SOURCE_DIR / f_name
        if not faction_dir.exists():
            print(f"  WARNING: Faction dir not found: {faction_dir}")
            continue

        for keyword_dir in sorted(faction_dir.iterdir()):
            if not keyword_dir.is_dir():
                continue
            keyword = keyword_dir.name

            for pdf_file in sorted(keyword_dir.glob("M4E_Stat_*.pdf")):
                name = pdf_file.stem

                # Skip alt-art variants (_B, _C, _D, etc.) — only process _A or no suffix
                if re.search(r'_[B-Z]$', name):
                    continue

                pdfs.append((pdf_file, f_name, keyword))

    return pdfs


def process_one_card(pdf_path, faction, keyword, conn=None, dry_run=False, save_json=False):
    """
    Process a single stat card PDF through the full pipeline.

    Returns dict with status, card data, and any issues.
    """
    result = {
        "pdf": str(pdf_path.name),
        "faction": faction,
        "keyword": keyword,
        "status": "ok",
        "issues": [],
    }

    try:
        # Step 1: Extract text from PDF
        extracted = extract_stat_card_text(str(pdf_path), faction=faction)
        if "error" in extracted:
            result["status"] = "extract_error"
            result["issues"].append(extracted["error"])
            return result

        front = extracted["front"]
        back = extracted["back"]

        # Step 2: Merge front + back
        merged = merge_stat_card(front, back, source_pdf=str(pdf_path))

        # Step 3: Validate
        validation = validate_card(merged)
        if not validation.passed:
            result["issues"].extend(
                [f"HARD: {v}" for v in validation.hard_violations])
        if validation.needs_review:
            result["issues"].extend(
                [f"SOFT: {f}" for f in validation.soft_flags])
            result["issues"].extend(
                [f"HALLUC: {h}" for h in validation.hallucination_flags])

        result["name"] = merged.get("name", "?")
        result["title"] = merged.get("title")
        result["validation_passed"] = validation.passed

        # Save intermediate JSON if requested
        if save_json:
            json_dir = WORK_DIR / faction / keyword
            json_dir.mkdir(parents=True, exist_ok=True)
            json_path = json_dir / f"{pdf_path.stem}_merged.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)

        # Step 4: Load into DB (unless dry-run or validation failed)
        if not validation.passed:
            result["db_status"] = "skipped_validation_fail"
            result["status"] = "validation_fail"
        elif dry_run:
            result["db_status"] = "dry_run"
        elif conn is not None:
            load_result = load_stat_card(conn, merged, replace=True)
            result["db_status"] = load_result.get("status", "unknown")

    except Exception as e:
        result["status"] = "exception"
        result["issues"].append(f"Exception: {type(e).__name__}: {e}")

    return result


def compare_with_db(pdf_path, faction, keyword, conn):
    """
    Extract card data and compare against existing DB values.

    Returns dict with field-by-field comparison.
    """
    result = {
        "pdf": str(pdf_path.name),
        "faction": faction,
        "keyword": keyword,
        "diffs": [],
    }

    try:
        extracted = extract_stat_card_text(str(pdf_path), faction=faction)
        if "error" in extracted:
            result["diffs"].append(f"EXTRACT_ERROR: {extracted['error']}")
            return result

        merged = merge_stat_card(
            extracted["front"], extracted["back"], source_pdf=str(pdf_path))
        name = merged.get("name", "?")
        title = merged.get("title")
        result["name"] = name

        # Look up existing DB record
        c = conn.cursor()
        c.execute(
            "SELECT * FROM models WHERE name=? AND title IS ? AND faction=?",
            (name, title, faction))
        row = c.fetchone()

        if not row:
            result["diffs"].append("NOT_IN_DB")
            return result

        # Compare key fields
        col_names = [desc[0] for desc in c.description]
        db_record = dict(zip(col_names, row))

        compare_fields = {
            "df": merged.get("df"),
            "wp": merged.get("wp"),
            "sz": merged.get("sz"),
            "sp": merged.get("sp"),
            "health": merged.get("health"),
            "cost": merged.get("cost"),
            "station": merged.get("station"),
            "base_size": merged.get("base_size"),
        }

        for field, new_val in compare_fields.items():
            db_val = db_record.get(field)
            if new_val is not None and str(new_val) != str(db_val):
                result["diffs"].append(f"{field}: DB={db_val} NEW={new_val}")

    except Exception as e:
        result["diffs"].append(f"EXCEPTION: {e}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Batch process M4E stat cards from PDF text layers")
    parser.add_argument("--faction", help="Process a single faction")
    parser.add_argument("--all", action="store_true", help="Process all factions")
    parser.add_argument("--dry-run", action="store_true",
                        help="Extract + validate only, don't write to DB")
    parser.add_argument("--compare-only", action="store_true",
                        help="Compare extractions against existing DB")
    parser.add_argument("--save-json", action="store_true",
                        help="Save intermediate merged JSON to pipeline_work/")
    parser.add_argument("--db", default=str(DB_PATH),
                        help="Database path (default: db/m4e.db)")
    parser.add_argument("--keyword", help="Filter to a specific keyword folder")
    parser.add_argument("--limit", type=int, help="Process at most N cards")
    args = parser.parse_args()

    if not args.faction and not args.all:
        parser.error("Specify --faction NAME or --all")

    faction = args.faction if args.faction else None

    # Discover PDFs
    pdfs = discover_stat_pdfs(faction=faction)
    if args.keyword:
        pdfs = [(p, f, k) for p, f, k in pdfs if k == args.keyword]
    if args.limit:
        pdfs = pdfs[:args.limit]

    print(f"Discovered {len(pdfs)} stat card PDFs")

    if not pdfs:
        print("No PDFs found. Check source_pdfs/ directory.")
        return

    # Connect to DB
    conn = None
    if not args.dry_run:
        conn = init_db(args.db)

    # Process
    start = time.time()
    results = []
    ok_count = 0
    fail_count = 0
    skip_count = 0

    for i, (pdf_path, f_name, kw_name) in enumerate(pdfs, 1):
        pct = i / len(pdfs) * 100
        short_name = pdf_path.stem.replace("M4E_Stat_", "")

        if args.compare_only:
            r = compare_with_db(pdf_path, f_name, kw_name, conn)
            if r["diffs"]:
                print(f"  [{i:3d}/{len(pdfs)}] {pct:5.1f}% DIFF {f_name}/{kw_name}/{short_name}: {r['diffs']}")
                fail_count += 1
            else:
                ok_count += 1
        else:
            r = process_one_card(
                pdf_path, f_name, kw_name, conn=conn,
                dry_run=args.dry_run, save_json=args.save_json)

            status_icon = {
                "ok": "+", "dry_run": ".", "validation_fail": "!",
                "extract_error": "X", "exception": "E",
            }.get(r["status"], "?")

            if r["status"] in ("ok",):
                ok_count += 1
            elif r["status"] == "validation_fail":
                fail_count += 1
            elif r["status"] in ("extract_error", "exception"):
                fail_count += 1
            else:
                skip_count += 1

            name = r.get("name", "?")
            if r["issues"]:
                print(f"  [{i:3d}/{len(pdfs)}] {pct:5.1f}% {status_icon} {f_name}/{kw_name}/{short_name} ({name})")
                for iss in r["issues"]:
                    print(f"         {iss}")
            elif i % 25 == 0 or i == len(pdfs):
                # Progress update every 25 cards
                elapsed = time.time() - start
                rate = i / elapsed if elapsed > 0 else 0
                print(f"  [{i:3d}/{len(pdfs)}] {pct:5.1f}% ok={ok_count} fail={fail_count} ({rate:.1f} cards/sec)")

        results.append(r)

    # Commit DB changes
    if conn and not args.dry_run and not args.compare_only:
        conn.commit()
        conn.close()
    elif conn:
        conn.close()

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"Processed {len(pdfs)} cards in {elapsed:.1f}s")
    print(f"  OK: {ok_count}  Fail: {fail_count}  Skip: {skip_count}")

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
