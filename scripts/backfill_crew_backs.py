#!/usr/bin/env python3
"""
backfill_crew_backs.py — Backfill crew card backs (markers + tokens) into existing data.

All 130+ crew card back PNGs already exist in pipeline_work/ from prior PDF splitting.
This script sends each back image through the vision API, then merges the extracted
markers/tokens into the existing front-only merged JSON files.

Usage:
    # Preview what would be processed
    python scripts/backfill_crew_backs.py --dry-run

    # Process all crew card backs
    python scripts/backfill_crew_backs.py

    # Process one faction only
    python scripts/backfill_crew_backs.py --faction Bayou

    # Set API rate limiting delay (default: 1.5s)
    python scripts/backfill_crew_backs.py --delay 2.0

    # Rebuild DB and re-export after backfill
    python scripts/backfill_crew_backs.py --reload-db --db db/m4e.db

Requires: ANTHROPIC_API_KEY environment variable
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

# Ensure sibling modules are importable
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic SDK required. Install: pip install anthropic")
    sys.exit(1)

from card_extractor import extract_crew_card_back
from merger import merge_crew_card


def find_crew_back_pairs(work_dir: Path, faction: str = None) -> list[dict]:
    """
    Scan pipeline_work/ for crew card back PNGs paired with existing merged JSONs.

    Returns list of dicts:
        {"back_png": Path, "merged_json": Path, "faction": str, "stem": str}
    """
    pairs = []

    # Crew card backs can be at root level or in faction subdirs
    search_dirs = []
    if faction:
        # Search faction subdir and root (some are at root level)
        faction_dir = work_dir / faction
        if faction_dir.is_dir():
            search_dirs.append(faction_dir)
        search_dirs.append(work_dir)
    else:
        # Search all faction subdirs and root
        search_dirs.append(work_dir)
        for child in sorted(work_dir.iterdir()):
            if child.is_dir():
                search_dirs.append(child)

    seen_stems = set()

    for search_dir in search_dirs:
        for back_png in sorted(search_dir.glob("M4E_Crew_*_back.png")):
            stem = back_png.name.replace("_back.png", "")

            if stem in seen_stems:
                continue
            seen_stems.add(stem)

            # Find corresponding merged JSON (same directory)
            merged_json = back_png.parent / f"{stem}_merged.json"

            # Determine faction from parent dir name (or "Unknown" if at root)
            parent_name = back_png.parent.name
            card_faction = parent_name if parent_name != work_dir.name else "Unknown"

            # Filter by faction if specified
            if faction and card_faction != faction and card_faction != "Unknown":
                continue

            pairs.append({
                "back_png": back_png,
                "merged_json": merged_json if merged_json.exists() else None,
                "faction": card_faction,
                "stem": stem,
            })

    return pairs


def backfill_single(client: anthropic.Anthropic, back_png: Path,
                    merged_json: Path = None) -> dict:
    """
    Extract back data from a crew card back PNG and merge into existing data.

    If merged_json exists, loads it and merges back data into it.
    If not, returns the back extraction standalone.

    Returns merged dict or {"error": str}.
    """
    # Extract back image
    back_data = extract_crew_card_back(client, str(back_png))

    if "error" in back_data:
        return {"error": f"Back extraction failed: {back_data['error']}"}

    if merged_json is None:
        # No existing front data — return back-only result
        back_data["_backfill_note"] = "No existing merged JSON found; back-only extraction"
        return back_data

    # Load existing merged JSON (front-only data)
    with open(merged_json, encoding="utf-8") as f:
        front_data = json.load(f)

    # Merge back into front
    merged = merge_crew_card(front_data, back_data, front_data.get("source_pdf"))

    # Track backfill metadata
    merged["_backfill_meta"] = {
        "back_png": str(back_png),
        "markers_added": len(back_data.get("markers", [])),
        "tokens_added": len(back_data.get("tokens", [])),
    }

    return merged


def main():
    parser = argparse.ArgumentParser(
        description="Backfill crew card backs (markers + tokens) into existing data"
    )
    parser.add_argument("--work-dir", default=str(PROJECT_ROOT / "pipeline_work"),
                        help="Pipeline work directory (default: pipeline_work/)")
    parser.add_argument("--faction", help="Process only this faction")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be processed without making API calls")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="Delay between API calls in seconds (default: 1.5)")
    parser.add_argument("--reload-db", action="store_true",
                        help="Rebuild database after backfill")
    parser.add_argument("--db", default=str(PROJECT_ROOT / "db" / "m4e.db"),
                        help="Database path for --reload-db")
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    if not work_dir.is_dir():
        print(f"ERROR: Work directory not found: {work_dir}")
        sys.exit(1)

    # Find all crew card back+merged pairs
    pairs = find_crew_back_pairs(work_dir, args.faction)
    print(f"Found {len(pairs)} crew card back PNGs")

    if not pairs:
        print("Nothing to process.")
        return

    # Dry run: just list what would be processed
    if args.dry_run:
        has_merged = sum(1 for p in pairs if p["merged_json"])
        no_merged = sum(1 for p in pairs if not p["merged_json"])
        print(f"  With existing merged JSON: {has_merged}")
        print(f"  Without merged JSON (back-only): {no_merged}")
        print()
        for p in pairs:
            status = "MERGE" if p["merged_json"] else "BACK-ONLY"
            print(f"  [{status:9s}] {p['faction']:20s} {p['stem']}")
        return

    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY environment variable")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Process each back
    results = {"success": 0, "errors": 0, "skipped": 0}
    error_details = []

    for i, pair in enumerate(pairs):
        print(f"\n[{i+1}/{len(pairs)}] {pair['faction']}/{pair['stem']}")

        try:
            merged = backfill_single(client, pair["back_png"], pair["merged_json"])

            if "error" in merged:
                print(f"  ERROR: {merged['error']}")
                results["errors"] += 1
                error_details.append(f"{pair['stem']}: {merged['error']}")
                continue

            # Write updated merged JSON
            output_path = pair["back_png"].parent / f"{pair['stem']}_merged.json"
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2)

            markers = len(merged.get("markers", []))
            tokens = len(merged.get("tokens", []))
            print(f"  OK: {markers} markers, {tokens} tokens -> {output_path.name}")
            results["success"] += 1

        except Exception as e:
            print(f"  EXCEPTION: {e}")
            results["errors"] += 1
            error_details.append(f"{pair['stem']}: {e}")

        # Rate limiting
        if args.delay > 0 and i < len(pairs) - 1:
            time.sleep(args.delay)

    # Summary
    print(f"\n{'='*60}")
    print("BACKFILL SUMMARY")
    print(f"{'='*60}")
    print(f"Total processed: {len(pairs)}")
    print(f"Success:         {results['success']}")
    print(f"Errors:          {results['errors']}")
    if error_details:
        print("\nErrors:")
        for e in error_details:
            print(f"  - {e}")

    # Optionally reload DB
    if args.reload_db and results["success"] > 0:
        print(f"\nRebuilding database at {args.db}...")
        from db_loader import init_db, load_crew_card
        conn = init_db(args.db)

        loaded = 0
        for pair in pairs:
            merged_path = pair["back_png"].parent / f"{pair['stem']}_merged.json"
            if not merged_path.exists():
                continue
            with open(merged_path, encoding="utf-8") as f:
                card = json.load(f)
            if card.get("card_type") != "crew_card":
                continue
            result = load_crew_card(conn, card, replace=True)
            if result["status"] in ("inserted", "updated"):
                loaded += 1

        conn.close()
        print(f"Loaded {loaded} crew cards to database")


if __name__ == "__main__":
    main()
