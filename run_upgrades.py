"""
run_upgrades.py — Process upgrade cards through the M4E pipeline.

Scans source_pdfs/ for upgrade card PDFs and runs them through
extraction, validation, and database loading.

Usage:
    python run_upgrades.py                    # All factions
    python run_upgrades.py --faction Bayou    # Single faction
    python run_upgrades.py --keyword Kin      # Single keyword
    python run_upgrades.py --dry-run          # Preview only
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent / "scripts"))

from pdf_splitter import extract_card_images, classify_card_type
from card_extractor import extract_upgrade_card
from db_loader import init_db, load_upgrade_card, log_parse

try:
    import anthropic
except ImportError:
    print("ERROR: pip install anthropic")
    sys.exit(1)


ROOT = Path(__file__).parent
SOURCE_DIR = ROOT / "source_pdfs"
DB_PATH = ROOT / "db" / "m4e.db"
WORK_DIR = ROOT / "pipeline_work"

# Map folder prefixes to faction names
FACTION_MAP = {
    "Arcanists": "Arcanists",
    "Bayou": "Bayou",
    "Explorers_Society": "Explorer's Society",
    "Guild": "Guild",
    "Neverborn": "Neverborn",
    "Outcasts": "Outcasts",
    "Resurrectionists": "Resurrectionists",
    "Ten_Thunders": "Ten Thunders",
}

# Map keyword folder abbreviations to factions (for Versatile upgrades)
VERSATILE_FACTION_MAP = {
    "Exs-Versatile": "Explorer's Society",
    "Gld-Versatile": "Guild",
    "Nvb-Versatile": "Neverborn",
    "Out-Versatile": "Outcasts",
    "Res-": "Resurrectionists",
    "TT-Versatile": "Ten Thunders",
}


def collect_upgrade_pdfs(faction_filter=None, keyword_filter=None):
    """Collect all upgrade card PDFs from source_pdfs/."""
    upgrades = []
    
    for faction_dir in sorted(SOURCE_DIR.iterdir()):
        if not faction_dir.is_dir():
            continue
        
        faction_name = FACTION_MAP.get(faction_dir.name, faction_dir.name)
        if faction_filter and faction_name.lower() != faction_filter.lower():
            continue
        
        for keyword_dir in sorted(faction_dir.iterdir()):
            if not keyword_dir.is_dir():
                continue
            
            keyword = keyword_dir.name
            if keyword_filter and keyword.lower() != keyword_filter.lower():
                continue
            
            for pdf in sorted(keyword_dir.glob("M4E_Upgrade_*.pdf")):
                upgrades.append({
                    "path": pdf,
                    "faction": faction_name,
                    "keyword": keyword,
                    "name": pdf.stem,
                })
    
    return upgrades


def get_existing_upgrades(db_path):
    """Get set of upgrade names already in DB."""
    existing = set()
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        try:
            c = conn.cursor()
            c.execute("SELECT name FROM upgrades")
            existing = {row[0] for row in c.fetchall()}
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet
        conn.close()
    return existing


def process_upgrade(pdf_info, client, db_path, dry_run=False):
    """Process a single upgrade card PDF."""
    pdf_path = pdf_info["path"]
    faction = pdf_info["faction"]
    keyword = pdf_info["keyword"]
    
    stem = pdf_path.stem
    work = WORK_DIR / stem
    work.mkdir(parents=True, exist_ok=True)
    
    # Step 1: Extract images
    print(f"  Step 1: Extracting images...")
    images = extract_card_images(str(pdf_path), str(work))
    
    if not images or any("error" in img for img in images):
        error = next((img.get("error", "unknown") for img in images if "error" in img), "no images")
        return {"status": "error", "error": error}
    
    # Step 2: Vision extraction
    print(f"  Step 2: Vision model extraction...")
    img = images[0]
    card = extract_upgrade_card(client, img["image_path"])
    
    if "error" in card:
        return {"status": "error", "error": card["error"]}
    
    # Enrich with metadata
    card["faction"] = faction
    card["keyword"] = keyword
    card["source_pdf"] = str(pdf_path)
    
    # Save merged JSON
    merged_path = work / f"{stem}_merged.json"
    with open(merged_path, "w", encoding="utf-8") as f:
        json.dump(card, f, indent=2, ensure_ascii=False)
    
    # Step 3: Basic validation
    print(f"  Step 3: Validating...")
    issues = []
    if not card.get("name"):
        issues.append("Missing upgrade name")
    if not card.get("granted_abilities") and not card.get("granted_actions"):
        issues.append("No abilities or actions found")
    
    if issues:
        print(f"    ISSUES: {', '.join(issues)}")
    else:
        print(f"    OK: {card['name']}")
    
    # Step 4: Load to DB
    if dry_run:
        print(f"  Step 4: [DRY RUN] Skipping DB load")
        return {"status": "dry_run", "name": card.get("name", "?")}
    
    print(f"  Step 4: Loading to database...")
    conn = init_db(str(db_path))
    try:
        result = load_upgrade_card(conn, card)
        log_parse(conn, str(pdf_path), card.get("name", "?"), result["status"])
        conn.close()
        print(f"    {result['status'].upper()}: {card.get('name', '?')}")
        return result
    except Exception as e:
        conn.close()
        return {"status": "error", "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Process M4E upgrade cards")
    parser.add_argument("--faction", help="Filter by faction name")
    parser.add_argument("--keyword", help="Filter by keyword folder")
    parser.add_argument("--dry-run", action="store_true", help="Extract only, don't load DB")
    parser.add_argument("--delay", type=float, default=1.5, help="Delay between API calls")
    parser.add_argument("--model", default="claude-sonnet-4-5-20250929", help="Claude model")
    args = parser.parse_args()
    
    print("=" * 60)
    print("M4E Upgrade Card Processor")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY environment variable")
        sys.exit(1)
    
    # Override model
    import card_extractor
    card_extractor.MODEL = args.model
    
    client = anthropic.Anthropic(api_key=api_key)
    
    # Collect upgrade PDFs
    upgrades = collect_upgrade_pdfs(args.faction, args.keyword)
    print(f"\nFound {len(upgrades)} upgrade card PDFs")
    
    if not upgrades:
        print("No upgrade cards to process.")
        return
    
    # Check existing
    existing = get_existing_upgrades(DB_PATH)
    print(f"Already in DB: {len(existing)} upgrades")
    
    # Show breakdown by faction
    by_faction = {}
    for u in upgrades:
        by_faction.setdefault(u["faction"], []).append(u)
    for faction, cards in sorted(by_faction.items()):
        print(f"  {faction}: {len(cards)} upgrades")
    
    # Process
    stats = {"inserted": 0, "skipped": 0, "errors": 0, "total": len(upgrades)}
    start = time.time()
    
    for i, upgrade_info in enumerate(upgrades):
        print(f"\n[{i+1}/{len(upgrades)}]")
        print(f"{'—'*50}")
        print(f"Processing: {upgrade_info['path'].name}")
        print(f"  Faction: {upgrade_info['faction']}, Keyword: {upgrade_info['keyword']}")
        
        try:
            result = process_upgrade(upgrade_info, client, DB_PATH, args.dry_run)
            status = result.get("status", "error")
            
            if status == "inserted":
                stats["inserted"] += 1
            elif status in ("skipped", "dry_run"):
                stats["skipped"] += 1
            elif status == "updated":
                stats["inserted"] += 1
            else:
                stats["errors"] += 1
                print(f"  ERROR: {result.get('error', 'unknown')}")
        except Exception as e:
            stats["errors"] += 1
            print(f"  EXCEPTION: {e}")
        
        # Rate limit
        if i < len(upgrades) - 1 and args.delay > 0:
            time.sleep(args.delay)
    
    # Summary
    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"UPGRADE PROCESSING SUMMARY")
    print(f"{'='*60}")
    print(f"Total:     {stats['total']}")
    print(f"Inserted:  {stats['inserted']}")
    print(f"Skipped:   {stats['skipped']}")
    print(f"Errors:    {stats['errors']}")
    print(f"Time:      {elapsed:.1f}s")
    
    # Final DB count
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH))
        try:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM upgrades")
            print(f"\nDatabase: {c.fetchone()[0]} upgrade cards total")
        except:
            pass
        conn.close()
    
    print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
