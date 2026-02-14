#!/usr/bin/env python3
"""
run_faction.py — Process M4E stat cards for any faction.

This script handles the full workflow:
1. Seeds the database with already-validated models (from existing JSON)
2. Auto-detects keyword folders under source_pdfs/{Faction}/
3. Collects PDFs, deduplicates across folders, filters art variants
4. Runs the parsing pipeline for each new card
5. Exports updated JSON when complete

Usage (from repo root):
    python run_faction.py Outcasts --dry-run       # Test without DB writes
    python run_faction.py Outcasts --keyword Bandit # Process only one keyword
    python run_faction.py Outcasts                  # Process all keywords
    python run_faction.py Outcasts --list-only      # Just show what would be processed
    python run_faction.py Bayou                     # Works for any faction
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
DATA_DIR = REPO_ROOT / "data"
DB_DIR = REPO_ROOT / "db"

# Valid factions
VALID_FACTIONS = [
    "Guild", "Arcanists", "Neverborn", "Bayou",
    "Outcasts", "Resurrectionists", "Ten Thunders", "Explorers Society"
]

# Add scripts to path so pipeline can import its siblings
sys.path.insert(0, str(SCRIPTS_DIR))


# ── Faction-aware paths ────────────────────────────────────────────────────
def faction_source_dir(faction: str) -> Path:
    """Return the source_pdfs directory for a faction."""
    return REPO_ROOT / "source_pdfs" / faction


def faction_json_path(faction: str) -> Path:
    """Return the export JSON path for a faction."""
    slug = faction.lower().replace(" ", "_").replace("'", "")
    return DATA_DIR / f"all_cards_{slug}.json"


def detect_keywords(source_dir: Path) -> list:
    """Auto-detect keyword folders from source directory."""
    if not source_dir.exists():
        return []
    keywords = []
    for item in sorted(source_dir.iterdir()):
        if item.is_dir() and not item.name.startswith("."):
            # Check it actually contains PDFs
            pdfs = list(item.glob("*.pdf"))
            if pdfs:
                keywords.append(item.name)
    return keywords


# ── Models already in the database ─────────────────────────────────────────
def load_existing_models(json_path: Path) -> set:
    """Load names of already-parsed models from existing JSON."""
    if not json_path.exists():
        print(f"  No existing JSON at {json_path}, starting fresh")
        return set()
    
    with open(json_path, encoding="utf-8") as f:
        cards = json.load(f)
    
    existing = set()
    for card in cards:
        name = card.get("name", "").strip()
        title = card.get("title")
        if title:
            title = title.strip()
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


def collect_pdfs(keywords: list, source_dir: Path) -> tuple:
    """
    Collect all PDFs from the specified keyword folders.
    Deduplicates across folders and filters art variants (keeps _A only).
    Returns (list of Paths, list of skipped variant descriptions).
    """
    seen_bases = {}  # normalized_base -> (path, variant, keyword_folder)
    
    # Build keyword tag list dynamically from the folders we're scanning
    keyword_tags = ['_' + kw.replace(' ', '_') + '_' for kw in keywords]
    # Also add common cross-faction tags
    keyword_tags.extend([
        '_Versatile_', '_Tricksy_', '_Returned_', '_Crossroads_',
        '_December_', '_Jockey_', '_Lucky_Fate_'
    ])
    
    def normalize_base(base_name: str) -> str:
        """Normalize a base name for dedup comparison."""
        n = base_name
        # Strip keyword segments embedded in the name
        for tag in keyword_tags:
            prefix_end = n.find('_', n.find('Stat_') + 5) if 'Stat_' in n else -1
            if prefix_end > 0 and tag in n[prefix_end:]:
                n = n.replace(tag, '_', 1)
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
            # No A exists for this card — use whatever we have
            a_base = norm_base + "_A"
            no_suffix = norm_base
            has_primary = a_base in seen_bases or no_suffix in seen_bases
            if not has_primary:
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
    # Remove faction-Versatile prefix patterns
    s = re.sub(r'^[A-Za-z]+-?Versatile_', '', s)
    # Remove leading keyword-like segments (capitalized words before the model name)
    # Strip up to 3 keyword-style prefixes
    for _ in range(3):
        # Match patterns like "Big_Hat_", "Tri-Chi_", "Wizz-Bang_", "Tormented_" etc.
        m = re.match(r'^([A-Z][a-z]*[-_]?[A-Z]?[a-z]*)_', s)
        if m:
            candidate = m.group(1)
            # Don't strip if it looks like an actual model name (2+ words remain)
            rest = s[len(candidate)+1:]
            if '_' in rest or len(rest) > 3:
                s = rest
            else:
                break
        else:
            break
    # Remove art variant suffix
    base, variant = detect_art_variant(s)
    if variant:
        s = base
    # Convert underscores/hyphens to spaces
    s = s.replace('_', ' ').replace('-', ' ')
    return s


def normalize_for_comparison(name: str) -> str:
    """Normalize a model name for fuzzy matching."""
    return (name.lower()
            .replace("'", "")
            .replace("-", " ")
            .replace("  ", " ")
            .strip())


def seed_database(db_path: str, json_path: Path, faction: str):
    """Load existing validated cards into the database."""
    from db_loader import init_db, load_stat_card, load_crew_card
    
    if not json_path.exists():
        print("  No existing JSON to seed from")
        return 0
    
    with open(json_path, encoding="utf-8") as f:
        cards = json.load(f)
    
    conn = init_db(db_path)
    loaded = 0
    
    for card in cards:
        try:
            # Ensure factions list exists
            if "factions" not in card:
                detected = card.get("faction", faction)
                factions = list(set([detected, faction]))
                card["factions"] = factions
            result = load_stat_card(conn, card, replace=False)
            if result["status"] == "inserted":
                loaded += 1
        except Exception as e:
            print(f"  Seed error for {card.get('name', '?')}: {e}")
    
    conn.commit()
    conn.close()
    return loaded


def run_pipeline(pdfs: list, db_path: str, work_dir: str,
                 faction: str, dry_run: bool = False, delay: float = 1.5):
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
                dry_run=dry_run, replace=False, skip_existing=False,
                source_faction=faction
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


def export_faction_cards(db_path: str, output_path: Path, faction: str):
    """Export all cards for a faction from DB to JSON."""
    import sqlite3
    
    if not os.path.exists(db_path):
        print("  No database to export from")
        return
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get all models that belong to this faction (via junction table)
    c.execute("""
        SELECT DISTINCT m.* FROM models m
        JOIN model_factions mf ON m.id = mf.model_id
        WHERE mf.faction = ?
        ORDER BY m.name, m.title
    """, (faction,))
    models = [dict(row) for row in c.fetchall()]
    
    for model in models:
        mid = model["id"]
        
        # Keywords
        c.execute("SELECT keyword FROM model_keywords WHERE model_id=?", (mid,))
        model["keywords"] = [r["keyword"] for r in c.fetchall()]
        
        # Factions (all factions for this model, not just the one we filtered on)
        c.execute("SELECT faction FROM model_factions WHERE model_id=?", (mid,))
        factions = [r["faction"] for r in c.fetchall()]
        model["factions"] = factions if factions else [model.get("faction", "Unknown")]
        
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
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(models, f, indent=2)
    
    print(f"  Exported {len(models)} models to {output_path}")


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Process M4E stat cards for any faction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_faction.py Outcasts                  # Process all Outcasts keywords
  python run_faction.py Outcasts --keyword Bandit # Process only one keyword
  python run_faction.py Outcasts --list-only      # Preview what would be processed
  python run_faction.py Outcasts --dry-run        # Extract + validate, no DB writes
  python run_faction.py Bayou                     # Works for any faction
        """
    )
    parser.add_argument("faction", 
                        help=f"Faction to process. Valid: {', '.join(VALID_FACTIONS)}")
    parser.add_argument("--keyword", "-k",
                        help="Process only a specific keyword (must match folder name)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Extract and validate only, don't write to DB")
    parser.add_argument("--list-only", action="store_true",
                        help="Just list what would be processed, no API calls")
    parser.add_argument("--include-upgrades", action="store_true",
                        help="Include upgrade cards (skipped by default)")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="Seconds between API calls (default: 1.5)")
    parser.add_argument("--db", default=str(DB_DIR / "m4e.db"),
                        help="Database path")
    parser.add_argument("--work-dir",
                        help="Working directory for intermediates (default: pipeline_work/{faction})")
    args = parser.parse_args()
    
    # Validate faction
    faction = args.faction
    if faction not in VALID_FACTIONS:
        # Try case-insensitive match
        for vf in VALID_FACTIONS:
            if vf.lower() == faction.lower():
                faction = vf
                break
        else:
            print(f"ERROR: Unknown faction '{faction}'")
            print(f"Valid factions: {', '.join(VALID_FACTIONS)}")
            sys.exit(1)
    
    # Resolve faction-specific paths
    source_dir = faction_source_dir(faction)
    json_path = faction_json_path(faction)
    work_dir = args.work_dir or str(REPO_ROOT / "pipeline_work" / faction)
    
    if not source_dir.exists():
        print(f"ERROR: Source directory not found: {source_dir}")
        print(f"Expected folder structure: source_pdfs/{faction}/<Keyword>/M4E_*.pdf")
        sys.exit(1)
    
    # Ensure directories exist
    DB_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # Auto-detect keywords
    all_keywords = detect_keywords(source_dir)
    if not all_keywords:
        print(f"ERROR: No keyword folders with PDFs found in {source_dir}")
        sys.exit(1)
    
    # Validate --keyword if specified
    if args.keyword:
        if args.keyword not in all_keywords:
            # Try case-insensitive match
            for kw in all_keywords:
                if kw.lower() == args.keyword.lower():
                    args.keyword = kw
                    break
            else:
                print(f"ERROR: Keyword '{args.keyword}' not found in {source_dir}")
                print(f"Available keywords: {', '.join(all_keywords)}")
                sys.exit(1)
    
    keywords = [args.keyword] if args.keyword else all_keywords
    
    print("=" * 60)
    print(f"M4E Parser — {faction}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"  Source: {source_dir}")
    print(f"  Keywords: {', '.join(keywords)}")
    print(f"  Database: {args.db}")
    
    # Step 1: Figure out what we already have
    print(f"\n[1/5] Loading existing models...")
    existing = load_existing_models(json_path)
    print(f"  Found {len(existing)} existing models in {json_path.name}")
    
    # Step 2: Collect PDFs
    print(f"\n[2/5] Collecting PDFs from {len(keywords)} keyword folder(s)...")
    pdfs, skipped_variants = collect_pdfs(keywords, source_dir)
    
    print(f"  Found {len(pdfs)} unique cards (after dedup + variant filtering)")
    if skipped_variants:
        print(f"  Skipped {len(skipped_variants)} art variants")
    
    # Step 3: Filter out already-parsed models
    new_pdfs = []
    already_done = []
    
    for pdf in pdfs:
        guessed_name = guess_model_name(pdf.stem)
        guessed_norm = normalize_for_comparison(guessed_name)
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
    
    # Filter out upgrades unless explicitly included
    if not args.include_upgrades:
        upgrade_pdfs = [p for p in new_pdfs if classify_card(p.stem) == "upgrade"]
        if upgrade_pdfs:
            new_pdfs = [p for p in new_pdfs if classify_card(p.stem) != "upgrade"]
            print(f"\n  Skipping {len(upgrade_pdfs)} upgrade cards (use --include-upgrades to process)")
            for up in upgrade_pdfs:
                print(f"    - {up.name}")
            print(f"  Adjusted to process: {len(new_pdfs)}")
    
    # Categorize
    stat_count = sum(1 for p in new_pdfs if classify_card(p.stem) == "stat")
    crew_count = sum(1 for p in new_pdfs if classify_card(p.stem) == "crew")
    upgrade_count = sum(1 for p in new_pdfs if classify_card(p.stem) == "upgrade")
    
    print(f"\n  Breakdown: {stat_count} stat cards, {crew_count} crew cards, {upgrade_count} upgrades")
    api_calls = (stat_count * 2) + crew_count + (upgrade_count * 2)
    print(f"  Estimated API calls: ~{api_calls}")
    
    # List mode
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
        # Seed from ALL existing faction JSONs, not just the current one
        total_seeded = 0
        for vf in VALID_FACTIONS:
            vf_json = faction_json_path(vf)
            if vf_json.exists():
                loaded = seed_database(args.db, vf_json, vf)
                if loaded > 0:
                    print(f"  Seeded {loaded} models from {vf_json.name}")
                    total_seeded += loaded
        if total_seeded == 0:
            # Initialize empty DB
            from db_loader import init_db
            conn = init_db(args.db)
            conn.close()
            print(f"  Initialized empty database")
        else:
            print(f"  Total seeded: {total_seeded}")
    else:
        print(f"  Database already exists, skipping seed")
    
    # Step 5: Run pipeline
    if len(new_pdfs) == 0:
        print(f"\n[4/5] Nothing new to process!")
    else:
        print(f"\n[4/5] Running pipeline on {len(new_pdfs)} cards...")
        print(f"  Delay between calls: {args.delay}s")
        
        if args.dry_run:
            print("  *** DRY RUN — no DB writes ***")
        
        stats = run_pipeline(new_pdfs, args.db, work_dir,
                             faction=faction, dry_run=args.dry_run, delay=args.delay)
        print(f"\n{stats.summary()}")
    
    # Step 6: Export updated JSON
    if not args.dry_run:
        print(f"\n[5/5] Exporting {faction} JSON...")
        export_faction_cards(args.db, json_path, faction)
    else:
        print(f"\n[5/5] Skipping export (dry run)")
    
    print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Don't forget to commit your changes in GitHub Desktop!")


if __name__ == "__main__":
    main()
