#!/usr/bin/env python3
"""
backfill_crew_markers.py — Extract marker definitions from existing crew card front PNGs
and populate both the per-card crew_markers table and the global markers registry.

All crew card front PNGs already exist in pipeline_work/. This script:
1. Finds all *Crew*_front.png files
2. Sends each to Claude API with crew_card_markers_prompt (focused on Markers section)
3. Matches extracted markers to existing crew_cards in DB by name
4. Updates crew_markers + crew_marker_terrain_traits tables
5. Populates global markers + marker_terrain_traits + marker_crew_sources tables
6. Seeds universal markers (Scheme, Remains, Strategy) from rulebook
7. Scans all model text to populate marker_model_sources

Usage:
    python backfill_crew_markers.py --dry-run        # Extract only, don't update DB
    python backfill_crew_markers.py --apply           # Extract and update DB
    python backfill_crew_markers.py --faction Guild --apply  # Single faction
    python backfill_crew_markers.py --scan-only --apply      # Skip API, just run text scan
"""
import argparse
import json
import os
import re
import sys
import time
import sqlite3
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
PIPELINE_WORK = REPO_ROOT / "pipeline_work"
DB_PATH = REPO_ROOT / "db" / "m4e.db"

sys.path.insert(0, str(SCRIPTS_DIR))

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic SDK required. Install: pip install anthropic")
    sys.exit(1)

from card_extractor import extract_crew_card_markers


# ============================================================
# Universal marker definitions from M4E rulebook (pp. 46-47)
# ============================================================
UNIVERSAL_MARKERS = [
    {
        "name": "Scheme",
        "category": "universal",
        "subcategory": "scheme",
        "default_size": "30mm",
        "default_height": "Ht 0",
        "terrain_traits": [],
        "rules_text": "Scheme markers are primarily made or removed with the Interact action. "
                      "Scheme markers do not do anything on their own but are often used in "
                      "conjunction with the abilities and actions of various models. They are "
                      "also used to gain victory points, most often from certain Schemes.",
    },
    {
        "name": "Remains",
        "category": "universal",
        "subcategory": "remains",
        "default_size": "30mm",
        "default_height": "Ht 0",
        "terrain_traits": [],
        "rules_text": "Remains markers are Ht 0 markers that are made by a model when it is killed. "
                      "Peons do not make Remains markers.",
    },
    {
        "name": "Strategy",
        "category": "universal",
        "subcategory": "strategy",
        "default_size": "30mm",
        "default_height": "Ht 0",
        "terrain_traits": [],
        "rules_text": "Strategy markers are often put on the table by the strategy or the players "
                      "throughout the game. Unless otherwise noted by the strategy, strategy markers "
                      "are neutral (neither friendly nor enemy) to all crews. Strategy markers ignore "
                      "and are ignored by the abilities, actions, triggers, etc. of models, except by "
                      "those effects which specifically call out Strategy markers. Models may move "
                      "through, but not end a move overlapping, Strategy markers.",
    },
]


def find_crew_back_pngs(faction: str = None) -> list:
    """Find all crew card back PNGs in pipeline_work.

    Markers are defined on crew card BACKS (above the Tokens section),
    not on the fronts. We use the merged JSON from the front to get the card name.
    """
    results = []

    if faction:
        search_dirs = [PIPELINE_WORK / faction]
    else:
        search_dirs = [PIPELINE_WORK]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for png in sorted(search_dir.rglob("*Crew*_back.png")):
            merged_json = png.parent / png.name.replace("_back.png", "_merged.json")
            results.append({
                "back_png": png,
                "merged_json": merged_json,
            })
    return results


def get_crew_card_name(merged_json: Path) -> str:
    """Read the crew card name from the existing merged JSON."""
    if merged_json.exists():
        with open(merged_json, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("name", "")
    return ""


def get_crew_card_keyword(merged_json: Path) -> str:
    """Infer the keyword from the PNG filename.

    Filenames follow: M4E_Crew_{Keyword}_{Master}_{Title}_back.png
    E.g., M4E_Crew_December_Rasputina_Abominable_back.png -> December
    """
    import re
    name = merged_json.stem  # e.g., M4E_Crew_December_Rasputina_Abominable_merged
    match = re.match(r"M4E_Crew_([^_]+)_", name)
    if match:
        raw = match.group(1)
        # Map folder-style names to actual keyword names
        keyword_map = {
            "Big-Hat": "Big Hat",
            "Last-Blossom": "Last Blossom",
            "Tri-Chi": "Tri-Chi",
            "Wizz-Bang": "Wizz-Bang",
            "Witch-Hunter": "Witch Hunter",
            "Qi-and-Gong": "Qi and Gong",
            "Red-Library": "Red Library",
        }
        return keyword_map.get(raw, raw)
    return ""


def upsert_global_marker(conn, name: str, category: str = "keyword_specific",
                         subcategory: str = None, default_size: str = "30mm",
                         default_height: str = "Ht 0", terrain_traits: list = None,
                         rules_text: str = None, keyword: str = None) -> int:
    """Insert or update a marker in the global registry. Returns marker id."""
    c = conn.cursor()
    traits_csv = ", ".join(sorted(terrain_traits)) if terrain_traits else None

    c.execute("SELECT id FROM markers WHERE name=?", (name,))
    row = c.fetchone()

    if row:
        marker_id = row[0]
        # Update with richer data if available
        c.execute("""UPDATE markers SET
            category = COALESCE(?, category),
            subcategory = COALESCE(?, subcategory),
            default_size = COALESCE(?, default_size),
            default_height = COALESCE(?, default_height),
            terrain_traits_csv = COALESCE(?, terrain_traits_csv),
            rules_text = COALESCE(?, rules_text),
            keyword = COALESCE(?, keyword)
            WHERE id=?""",
            (category, subcategory, default_size, default_height,
             traits_csv, rules_text, keyword, marker_id))
    else:
        c.execute("""INSERT INTO markers
            (name, category, subcategory, default_size, default_height,
             terrain_traits_csv, rules_text, keyword)
            VALUES (?,?,?,?,?,?,?,?)""",
            (name, category, subcategory, default_size, default_height,
             traits_csv, rules_text, keyword))
        marker_id = c.lastrowid

    # Update normalized terrain traits
    if terrain_traits:
        c.execute("DELETE FROM marker_terrain_traits WHERE marker_id=?", (marker_id,))
        for trait in terrain_traits:
            c.execute("INSERT OR IGNORE INTO marker_terrain_traits (marker_id, trait) VALUES (?,?)",
                      (marker_id, trait))

    return marker_id


def update_crew_markers(conn, crew_card_name: str, markers: list, keyword: str = "") -> dict:
    """Replace markers for a crew card in the database and update global registry."""
    c = conn.cursor()
    c.execute("SELECT id FROM crew_cards WHERE name=?", (crew_card_name,))
    row = c.fetchone()
    if not row:
        return {"status": "not_found", "name": crew_card_name}

    crew_id = row[0]

    # Delete existing crew_markers for this card
    old_count = c.execute(
        "SELECT COUNT(*) FROM crew_markers WHERE crew_card_id=?", (crew_id,)
    ).fetchone()[0]
    # Delete terrain traits first (cascade should handle but be explicit)
    c.execute("""DELETE FROM crew_marker_terrain_traits WHERE marker_id IN
        (SELECT id FROM crew_markers WHERE crew_card_id=?)""", (crew_id,))
    c.execute("DELETE FROM crew_markers WHERE crew_card_id=?", (crew_id,))

    # Delete old marker_crew_sources for this crew card
    c.execute("DELETE FROM marker_crew_sources WHERE crew_card_id=?", (crew_id,))

    # Insert new crew_markers and update global registry
    for marker in markers:
        name = marker["name"]
        size = marker.get("size")
        height = marker.get("height")
        text = marker.get("text")
        traits = marker.get("terrain_traits", [])

        # Insert into per-card crew_markers table
        c.execute("""INSERT INTO crew_markers (crew_card_id, name, size, height, text)
            VALUES (?,?,?,?,?)""", (crew_id, name, size, height, text))
        crew_marker_id = c.lastrowid
        for trait in traits:
            c.execute("INSERT INTO crew_marker_terrain_traits VALUES (?,?)",
                      (crew_marker_id, trait))

        # Upsert into global markers registry
        marker_id = upsert_global_marker(
            conn, name=name, category="keyword_specific",
            default_size=size or "30mm", default_height=height or "Ht 0",
            terrain_traits=traits, rules_text=text, keyword=keyword or None
        )

        # Link marker to crew card
        c.execute("INSERT OR IGNORE INTO marker_crew_sources (marker_id, crew_card_id) VALUES (?,?)",
                  (marker_id, crew_id))

    conn.commit()
    return {
        "status": "updated", "crew_id": crew_id,
        "name": crew_card_name, "marker_count": len(markers),
        "old_count": old_count,
    }


def seed_universal_markers(conn):
    """Seed the 3 universal marker types from the rulebook."""
    print("\nSeeding universal markers (Scheme, Remains, Strategy)...")
    for m in UNIVERSAL_MARKERS:
        marker_id = upsert_global_marker(
            conn, name=m["name"], category=m["category"],
            subcategory=m["subcategory"], default_size=m["default_size"],
            default_height=m["default_height"], terrain_traits=m["terrain_traits"],
            rules_text=m["rules_text"], keyword=None
        )
        print(f"  {m['name']}: id={marker_id}")
    conn.commit()


def scan_model_text_for_markers(conn):
    """Scan all model text fields for marker references and populate marker_model_sources."""
    print("\nScanning model text for marker references...")
    c = conn.cursor()

    # Get all known marker names
    c.execute("SELECT id, name FROM markers ORDER BY length(name) DESC")
    known_markers = [(row[0], row[1]) for row in c.fetchall()]
    if not known_markers:
        print("  No markers in registry to scan for.")
        return

    # Build pattern matching marker names
    # Sort by length descending so "Ice Pillar" matches before "Ice"
    marker_patterns = []
    for marker_id, marker_name in known_markers:
        # Match "Name marker" or "Name markers"
        pattern = re.compile(
            r'\b' + re.escape(marker_name) + r'\s+markers?\b',
            re.IGNORECASE
        )
        marker_patterns.append((marker_id, marker_name, pattern))

    # Clear existing model sources
    c.execute("DELETE FROM marker_model_sources")

    # Patterns for determining relationship
    create_words = {"make", "makes", "making", "made", "summon", "summons", "summoned",
                    "place", "places", "placed", "create", "creates", "created"}
    remove_words = {"remove", "removes", "removed", "removing", "discard", "discards",
                    "destroy", "destroys", "destroyed"}

    insertions = 0

    def scan_text(text, model_id, source_type, source_name):
        nonlocal insertions
        if not text:
            return
        for marker_id, marker_name, pattern in marker_patterns:
            for match in pattern.finditer(text):
                # Determine relationship from context
                start = max(0, match.start() - 30)
                context = text[start:match.end() + 10].lower()
                if any(w in context for w in create_words):
                    relationship = "creates"
                elif any(w in context for w in remove_words):
                    relationship = "removes"
                else:
                    relationship = "references"

                c.execute("""INSERT INTO marker_model_sources
                    (marker_id, model_id, source_type, source_name, relationship)
                    VALUES (?,?,?,?,?)""",
                    (marker_id, model_id, source_type, source_name, relationship))
                insertions += 1

    # Scan model abilities
    c.execute("SELECT a.model_id, a.name, a.text FROM abilities a")
    for row in c.fetchall():
        scan_text(row[2], row[0], "ability", row[1])

    # Scan model actions (effects text)
    c.execute("SELECT a.model_id, a.name, a.effects FROM actions a")
    for row in c.fetchall():
        scan_text(row[2], row[0], "action_effect", row[1])

    # Scan model triggers
    c.execute("""SELECT a.model_id, t.name, t.text, a.name as action_name
        FROM triggers t JOIN actions a ON t.action_id = a.id""")
    for row in c.fetchall():
        source = f"{row[3]} > {row[1]}"
        scan_text(row[2], row[0], "trigger", source)

    # Scan crew card abilities
    c.execute("""SELECT cc.id, ka.name, ka.text
        FROM crew_keyword_abilities ka JOIN crew_cards cc ON ka.crew_card_id = cc.id""")
    # Note: crew abilities don't have a model_id, skip for now (they're crew-level)

    # Scan crew card action effects
    c.execute("""SELECT cc.id, ka.name, ka.effects
        FROM crew_keyword_actions ka JOIN crew_cards cc ON ka.crew_card_id = cc.id""")

    # Scan crew card triggers
    c.execute("""SELECT cc.id, t.name, t.text, ka.name as action_name
        FROM crew_keyword_action_triggers t
        JOIN crew_keyword_actions ka ON t.crew_action_id = ka.id
        JOIN crew_cards cc ON ka.crew_card_id = cc.id""")

    conn.commit()
    print(f"  Inserted {insertions} marker-model references")


def main():
    parser = argparse.ArgumentParser(description="Backfill crew card marker definitions")
    parser.add_argument("--apply", action="store_true", help="Update database")
    parser.add_argument("--dry-run", action="store_true", help="Extract only, don't update DB")
    parser.add_argument("--faction", help="Process only one faction subfolder")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="Seconds between API calls (default: 1.5)")
    parser.add_argument("--scan-only", action="store_true",
                        help="Skip API extraction, just run text scan and seed universals")
    args = parser.parse_args()

    if not args.apply and not args.dry_run:
        print("Specify --dry-run or --apply")
        sys.exit(1)

    conn = None
    if args.apply:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row

    if args.scan_only:
        if not conn:
            print("ERROR: --scan-only requires --apply")
            sys.exit(1)
        seed_universal_markers(conn)
        scan_model_text_for_markers(conn)
        conn.close()
        print("\nDone! (scan-only mode)")
        return

    # Setup API client
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY environment variable")
        sys.exit(1)
    client = anthropic.Anthropic(api_key=api_key)

    # Find back PNGs (markers are on crew card BACKS, above Tokens section)
    backs = find_crew_back_pngs(args.faction)
    print(f"Found {len(backs)} crew card back PNGs")

    # Process
    stats = {
        "extracted": 0, "has_markers": 0, "no_markers": 0,
        "updated": 0, "errors": 0, "not_found": 0, "skipped": 0,
        "total_markers": 0,
    }
    start_time = time.time()

    for i, entry in enumerate(backs):
        back_png = entry["back_png"]
        crew_name = get_crew_card_name(entry["merged_json"])
        keyword = get_crew_card_keyword(entry["merged_json"])

        if not crew_name:
            print(f"  [{i+1}/{len(backs)}] SKIP {back_png.name} (no merged JSON or missing name)")
            stats["skipped"] += 1
            continue

        print(f"  [{i+1}/{len(backs)}] {back_png.name} -> '{crew_name}'")

        # Extract markers from back
        result = extract_crew_card_markers(client, str(back_png))

        if "error" in result:
            print(f"    ERROR: {result['error']}")
            stats["errors"] += 1
            continue

        stats["extracted"] += 1
        has_markers = result.get("has_markers_section", False)
        markers = result.get("markers", [])

        if not has_markers or not markers:
            print(f"    No markers section")
            stats["no_markers"] += 1
            continue

        stats["has_markers"] += 1
        stats["total_markers"] += len(markers)
        marker_names = [m["name"] for m in markers]
        print(f"    {len(markers)} markers: {', '.join(marker_names)}")

        for m in markers:
            traits = m.get("terrain_traits", [])
            if traits:
                print(f"      {m['name']}: {m.get('size', '30mm')}, {m.get('height', 'Ht 0')}, [{', '.join(traits)}]")

        # Update DB
        if args.apply and conn:
            db_result = update_crew_markers(conn, crew_name, markers, keyword)
            if db_result["status"] == "updated":
                stats["updated"] += 1
                if db_result["old_count"]:
                    print(f"    DB: replaced {db_result['old_count']} -> {db_result['marker_count']} markers")
                else:
                    print(f"    DB: inserted {db_result['marker_count']} markers")
            elif db_result["status"] == "not_found":
                print(f"    WARNING: '{crew_name}' not found in crew_cards table")
                stats["not_found"] += 1

        # Rate limiting
        if i < len(backs) - 1:
            time.sleep(args.delay)

    # Post-extraction: seed universals and scan text
    if args.apply and conn:
        seed_universal_markers(conn)
        scan_model_text_for_markers(conn)

    if conn:
        # Print registry summary
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM markers")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM marker_terrain_traits")
        traits = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM marker_crew_sources")
        crew_src = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM marker_model_sources")
        model_src = cursor.fetchone()[0]
        print(f"\n  Global registry: {total} markers, {traits} terrain traits, "
              f"{crew_src} crew sources, {model_src} model references")
        conn.close()

    elapsed = time.time() - start_time

    # Summary
    print(f"\n{'='*50}")
    print(f"MARKER BACKFILL SUMMARY")
    print(f"{'='*50}")
    print(f"  Processed:     {len(backs)}")
    print(f"  Extracted:     {stats['extracted']}")
    print(f"  Has markers:   {stats['has_markers']}")
    print(f"  No markers:    {stats['no_markers']}")
    print(f"  Total markers: {stats['total_markers']}")
    print(f"  Updated DB:    {stats['updated']}")
    print(f"  Not found:     {stats['not_found']}")
    print(f"  Skipped:       {stats['skipped']}")
    print(f"  Errors:        {stats['errors']}")
    print(f"  Time:          {elapsed:.1f}s")


if __name__ == "__main__":
    main()
