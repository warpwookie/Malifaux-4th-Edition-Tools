#!/usr/bin/env python3
"""
run_bayou.py — Process remaining Bayou faction keyword cards.

This script handles the full workflow:
1. Seeds the database with already-validated models (from all_cards_bayou.json)
2. Collects PDFs from remaining keyword folders
3. Deduplicates across folders and filters art variants
4. Runs the parsing pipeline for each new card
5. Exports updated JSON when complete

Usage (from repo root):
    python run_bayou.py --dry-run          # Test without DB writes or API calls
    python run_bayou.py --keyword Kin      # Process only one keyword
    python run_bayou.py                    # Process all remaining keywords
    python run_bayou.py --list-only        # Just show what would be processed
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Resolve paths relative to this script (repo root) ──────────────────────
REPO_ROOT = Path(__file__).parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SOURCE_DIR = REPO_ROOT / "source_pdfs" / "Bayou"
DATA_DIR = REPO_ROOT / "data"
DB_DIR = REPO_ROOT / "db"
EXISTING_JSON = DATA_DIR / "all_cards_bayou.json"

# Add scripts to path so pipeline can import its siblings
sys.path.insert(0, str(SCRIPTS_DIR))

# ── Keywords to process ─────────────────────────────────────────────────────
REMAINING_KEYWORDS = ["Kin", "Sooey", "Tri-Chi", "Wizz-Bang", "Swampfiend"]

# ── Models already in the database (from Stage 1) ──────────────────────────
def load_existing_models() -> set:
    """Load names of already-parsed models from existing JSON."""
    if not EXISTING_JSON.exists():
        print(f"  Warning: {EXISTING_JSON} not found, starting fresh")
        return set()
    
    with open(EXISTING_JSON) as f:
        cards = json.load(f)
    
    # Use (name, title) tuple as the key since some models have multiple titles
    existing = set()
    for card in cards:
        name = card.get("name", "").strip()
        title = card.get("title")
        existing.add((name, title))
    
    return existing


def detect_art_variant(stem: str) -> tuple:
    """
    Check if filename ends with an art variant suffix (_A, _B, _C, etc.)
    Returns (base_name, variant_letter_or_empty).
    """
    parts = stem.rsplit("_", 1)
    if len(parts) == 2 and len(parts[1]) == 1 and parts[1].isalpha() and parts[1].isupper():
        return parts[0], parts[1]
    return stem, ""


def collect_pdfs(keywords: list, source_dir: Path) -> list:
    """
    Collect all PDFs from the specified keyword folders.
    Deduplicates across folders and filters art variants (keeps _A only).
    Returns list of Path objects.
    """
    # Known filename typos/inconsistencies -> canonical form
    FILENAME_FIXES = {
        "Lighting_Bug": "Lightning_Bug",   # Typo in Wizz-Bang folder
        "Hog-Whisperer": "Hog_Whisperer",  # Hyphen vs underscore inconsistency
    }
    
    seen_bases = {}  # normalized_base -> (path, variant, keyword_folder)
    
    def normalize_base(base_name: str) -> str:
        """Normalize a base name for dedup comparison."""
        n = base_name
        # Apply known filename typo fixes
        for wrong, right in FILENAME_FIXES.items():
            n = n.replace(wrong, right)
        # Strip secondary keyword tags that differ between folders
        # e.g., "M4E_Stat_Sooey_Kin_Swine_Twirler" vs "M4E_Stat_Sooey_Swine_Twirler"
        # Remove keyword segments embedded in the name
        keyword_tags = ['_Kin_', '_Sooey_', '_Swampfiend_', '_Tri-Chi_', '_Wizz-Bang_',
                        '_Infamous_', '_Tricksy_', '_Returned_']
        for tag in keyword_tags:
            # Only strip if it appears AFTER the card type prefix
            prefix_end = n.find('_', n.find('Stat_') + 5) if 'Stat_' in n else -1
            if prefix_end > 0 and tag in n[prefix_end:]:
                n = n.replace(tag, '_', 1)
                # Clean up double underscores
                while '__' in n:
                    n = n.replace('__', '_')
        return n
    
    for keyword in keywords:
        keyword_dir = source_dir / keyword
        if not keyword_dir.exists():
            print(f"  Warning: folder not found: {keyword_dir}")
            continue
        
        for pdf in sorted(keyword_dir.glob("*.pdf")):
            base, variant = detect_art_variant(pdf.stem)
            norm_base = normalize_base(base)
            
            if norm_base not in seen_bases:
                seen_bases[norm_base] = (pdf, variant, keyword)
            else:
                existing_path, existing_variant, existing_kw = seen_bases[norm_base]
                # Prefer variant A over B/C, or no-suffix over any suffix
                if variant == "" and existing_variant != "":
                    seen_bases[norm_base] = (pdf, variant, keyword)
                elif variant == "A" and existing_variant not in ("", "A"):
                    seen_bases[norm_base] = (pdf, variant, keyword)
                elif variant and existing_variant and variant < existing_variant:
                    seen_bases[norm_base] = (pdf, variant, keyword)
    
    # Filter: only keep primary variants (A or no suffix)
    result = []
    skipped_variants = []
    for norm_base, (pdf, variant, keyword) in sorted(seen_bases.items()):
        if variant == "" or variant == "A":
            result.append(pdf)
        else:
            # Check if this base has an A or no-suffix version
            has_primary = (variant == "A" or variant == "")
            if not has_primary:
                # No A exists for this card, use whatever we have
                result.append(pdf)
            else:
                skipped_variants.append(f"{pdf.name} (variant {variant}, using A instead)")
    
    return result, skipped_variants


def classify_card(stem: str) -> str:
    """Classify card type from filename."""
    s = stem.lower()
    if "_crew_" in s:
        return "crew"
    elif "_upgrade_" in s:
        return "upgrade"
    elif "_stat_" in s:
        return "stat"
    return "unknown"


def guess_model_name(stem: str) -> str:
    """
    Make a rough guess at the model name from the filename.
    Used for pre-filtering only — not for actual data extraction.
    """
    s = stem
    # Remove M4E prefix
    s = re.sub(r'^M4E_(Stat|Crew|Upgrade)_', '', s)
    # Remove Byu-Versatile prefix (with or without hyphen)
    s = re.sub(r'^Byu-?Versatile_', '', s)
    # Known keyword prefixes to strip (order matters — longer/compound first)
    known_kw = ['Big_Hat', 'BigHat', 'Tri-Chi', 'Wizz-Bang', 'Lucky_Fate',
                'Kin', 'Sooey', 'Swampfiend', 'Infamous', 'Tricksy', 
                'Returned', 'Crossroads', 'December', 'Jockey']
    # Strip up to three keyword prefixes (e.g., Byu-Versatile_Sooey_Jockey_Name)
    for _ in range(3):
        for kw in known_kw:
            if s.startswith(kw + '_'):
                s = s[len(kw)+1:]
                break
    # Remove art variant suffix
    base, variant = detect_art_variant(s)
    if variant:
        s = base
    # Convert underscores to spaces
    s = s.replace('_', ' ')
    # Normalize hyphens to spaces too
    s = s.replace('-', ' ')
    return s


def normalize_for_comparison(name: str) -> str:
    """Normalize a model name for fuzzy matching."""
    return (name.lower()
            .replace("'", "")
            .replace("-", " ")
            .replace("  ", " ")
            .strip())


def seed_database(db_path: str, json_path: Path):
    """Load existing validated cards into the database."""
    from db_loader import init_db, load_stat_card, load_crew_card
    
    if not json_path.exists():
        print("  No existing JSON to seed from")
        return 0
    
    with open(json_path) as f:
        cards = json.load(f)
    
    conn = init_db(db_path)
    loaded = 0
    
    for card in cards:
        try:
            result = load_stat_card(conn, card, replace=False)
            if result["status"] == "inserted":
                loaded += 1
        except Exception as e:
            print(f"  Seed error for {card.get('name', '?')}: {e}")
    
    conn.close()
    return loaded


def run_pipeline(pdfs: list, db_path: str, work_dir: str, 
                 dry_run: bool = False, delay: float = 1.5):
    """Run the parsing pipeline on a list of PDFs."""
    from pipeline import process_single_pdf, PipelineStats
    import anthropic
    
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY environment variable")
        sys.exit(1)
    
    client = anthropic.Anthropic(api_key=api_key)
    stats = PipelineStats()
    stats.total_pdfs = len(pdfs)
    
    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)
    
    for i, pdf in enumerate(pdfs):
        print(f"\n[{i+1}/{len(pdfs)}]", end="")
        
        try:
            result = process_single_pdf(
                str(pdf), db_path, client, work_dir, 
                dry_run=dry_run, replace=False, skip_existing=False
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
            import traceback
            traceback.print_exc()
        
        # Rate limiting
        if delay > 0 and i < len(pdfs) - 1:
            time.sleep(delay)
    
    return stats


def export_all_cards(db_path: str, output_path: Path):
    """Export all Bayou cards from DB to JSON."""
    import sqlite3
    
    if not os.path.exists(db_path):
        print("  No database to export from")
        return
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get all Bayou models
    c.execute("""
        SELECT * FROM models 
        WHERE faction = 'Bayou' 
        ORDER BY name, title
    """)
    models = [dict(row) for row in c.fetchall()]
    
    for model in models:
        mid = model["id"]
        
        # Keywords
        c.execute("SELECT keyword FROM model_keywords WHERE model_id=?", (mid,))
        model["keywords"] = [r["keyword"] for r in c.fetchall()]
        
        # Characteristics
        c.execute("SELECT characteristic FROM model_characteristics WHERE model_id=?", (mid,))
        model["characteristics"] = [r["characteristic"] for r in c.fetchall()]
        
        # Abilities
        c.execute("SELECT * FROM abilities WHERE model_id=? ORDER BY id", (mid,))
        model["abilities"] = [dict(r) for r in c.fetchall()]
        
        # Actions
        c.execute("SELECT * FROM actions WHERE model_id=? ORDER BY id", (mid,))
        actions = [dict(r) for r in c.fetchall()]
        for action in actions:
            aid = action["id"]
            c.execute("SELECT * FROM triggers WHERE action_id=? ORDER BY id", (aid,))
            action["triggers"] = [dict(r) for r in c.fetchall()]
        model["actions"] = actions
    
    conn.close()
    
    with open(output_path, "w") as f:
        json.dump(models, f, indent=2)
    
    print(f"  Exported {len(models)} models to {output_path}")


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Process remaining Bayou keyword cards")
    parser.add_argument("--keyword", "-k", choices=REMAINING_KEYWORDS,
                        help="Process only a specific keyword")
    parser.add_argument("--dry-run", action="store_true",
                        help="Extract and validate only, don't write to DB")
    parser.add_argument("--list-only", action="store_true",
                        help="Just list what would be processed, no API calls")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="Seconds between API calls (default: 1.5)")
    parser.add_argument("--db", default=str(DB_DIR / "m4e.db"),
                        help="Database path")
    parser.add_argument("--work-dir", default=str(REPO_ROOT / "pipeline_work"),
                        help="Working directory for intermediates")
    args = parser.parse_args()
    
    # Ensure db directory exists
    DB_DIR.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print("M4E Bayou Parser — Remaining Keywords")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Step 1: Figure out what we already have
    print("\n[1/5] Loading existing models...")
    existing = load_existing_models()
    print(f"  Found {len(existing)} existing models in database")
    
    # Step 2: Collect PDFs
    keywords = [args.keyword] if args.keyword else REMAINING_KEYWORDS
    print(f"\n[2/5] Collecting PDFs from: {', '.join(keywords)}...")
    pdfs, skipped_variants = collect_pdfs(keywords, SOURCE_DIR)
    
    print(f"  Found {len(pdfs)} unique cards (after dedup + variant filtering)")
    if skipped_variants:
        print(f"  Skipped {len(skipped_variants)} art variants")
    
    # Step 3: Filter out already-parsed models
    # We use a rough filename-to-name mapping for pre-filtering
    # The DB itself will also skip duplicates on insert
    new_pdfs = []
    already_done = []
    
    for pdf in pdfs:
        guessed_name = guess_model_name(pdf.stem)
        guessed_norm = normalize_for_comparison(guessed_name)
        # Check if any existing model name is close enough
        is_known = False
        for (name, title) in existing:
            existing_norm = normalize_for_comparison(name)
            if existing_norm == guessed_norm:
                is_known = True
                already_done.append(f"{pdf.name} -> {name}")
                break
        if not is_known:
            new_pdfs.append(pdf)
    
    print(f"  Already parsed: {len(already_done)}")
    print(f"  New to process: {len(new_pdfs)}")
    
    # Categorize what we're processing
    stat_count = sum(1 for p in new_pdfs if classify_card(p.stem) == "stat")
    crew_count = sum(1 for p in new_pdfs if classify_card(p.stem) == "crew")
    upgrade_count = sum(1 for p in new_pdfs if classify_card(p.stem) == "upgrade")
    
    print(f"\n  Breakdown: {stat_count} stat cards, {crew_count} crew cards, {upgrade_count} upgrades")
    api_calls = (stat_count * 2) + crew_count + (upgrade_count * 2)
    print(f"  Estimated API calls: ~{api_calls}")
    
    # List mode — just show what would be processed
    if args.list_only:
        print("\n  Cards to process:")
        for pdf in new_pdfs:
            ctype = classify_card(pdf.stem)
            print(f"    [{ctype:7s}] {pdf.name}")
        
        if already_done:
            print(f"\n  Already in DB (would skip):")
            for item in already_done:
                print(f"    {item}")
        return
    
    # Step 4: Seed database with existing models
    print(f"\n[3/5] Seeding database at {args.db}...")
    if not os.path.exists(args.db):
        loaded = seed_database(args.db, EXISTING_JSON)
        print(f"  Seeded {loaded} existing models")
    else:
        print(f"  Database already exists, skipping seed")
    
    # Step 5: Run pipeline
    if len(new_pdfs) == 0:
        print("\n[4/5] Nothing new to process!")
    else:
        print(f"\n[4/5] Running pipeline on {len(new_pdfs)} cards...")
        print(f"  Delay between calls: {args.delay}s")
        
        if args.dry_run:
            print("  *** DRY RUN — no DB writes ***")
        
        stats = run_pipeline(new_pdfs, args.db, args.work_dir, 
                             dry_run=args.dry_run, delay=args.delay)
        print(f"\n{stats.summary()}")
    
    # Step 6: Export updated JSON
    if not args.dry_run:
        print(f"\n[5/5] Exporting updated Bayou JSON...")
        export_path = DATA_DIR / "all_cards_bayou.json"
        export_all_cards(args.db, export_path)
    else:
        print(f"\n[5/5] Skipping export (dry run)")
    
    print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Don't forget to commit your changes in GitHub Desktop!")


if __name__ == "__main__":
    main()
