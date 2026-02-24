"""
final_audit.py — Comprehensive M4E database validation.

Runs multiple validation layers:
  1. Structural — missing required fields, invalid values
  2. Statistical — outlier detection for hallucinated stats
  3. Consistency — faction/keyword/station value checks
  4. Completeness — source PDFs vs DB coverage
  5. Duplicates — remaining name collisions
  6. Upgrades — basic structure checks
  7. Cross-table — crew cards reference valid masters, etc.

Usage:
    python final_audit.py
    python final_audit.py --verbose
    python final_audit.py --export report.json
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

DB_PATH = "db/m4e.db"
SOURCE_DIR = Path("source_pdfs")

# Valid enum values
VALID_FACTIONS = {
    "Arcanists", "Bayou", "Explorer's Society", "Guild",
    "Neverborn", "Outcasts", "Resurrectionists", "Ten Thunders"
}
VALID_STATIONS = {"Master", "Henchman", "Minion", "Totem", "Peon", None}
VALID_ACTION_TYPES = {"melee", "missile", "magic", "variable", None}
VALID_CATEGORIES = {"attack_actions", "tactical_actions"}
VALID_TIMINGS = {
    "when_resolving", "after_succeeding", "after_failing",
    "after_damaging", "when_declaring", "after_resolving", None
}
VALID_RESISTS = {"Df", "Wp", "Sz", "Sp", "Mv", None}
VALID_BASE_SIZES = {"30mm", "40mm", "50mm", None}

# Stat ranges (reasonable bounds for M4E)
STAT_RANGES = {
    "df": (2, 8),
    "wp": (2, 8),
    "sz": (1, 6),
    "sp": (3, 8),
    "health": (1, 16),
}


class AuditReport:
    def __init__(self):
        self.sections = {}
        self.error_count = 0
        self.warning_count = 0
        self.info_count = 0
    
    def add(self, section, level, message, details=None):
        if section not in self.sections:
            self.sections[section] = []
        self.sections[section].append({
            "level": level,
            "message": message,
            "details": details
        })
        if level == "ERROR":
            self.error_count += 1
        elif level == "WARNING":
            self.warning_count += 1
        else:
            self.info_count += 1
    
    def error(self, section, message, details=None):
        self.add(section, "ERROR", message, details)
    
    def warn(self, section, message, details=None):
        self.add(section, "WARNING", message, details)
    
    def info(self, section, message, details=None):
        self.add(section, "INFO", message, details)
    
    def print_report(self, verbose=False):
        print("\n" + "=" * 70)
        print("M4E DATABASE FINAL AUDIT REPORT")
        print("=" * 70)
        
        for section, items in self.sections.items():
            errors = [i for i in items if i["level"] == "ERROR"]
            warnings = [i for i in items if i["level"] == "WARNING"]
            infos = [i for i in items if i["level"] == "INFO"]
            
            print(f"\n{'─' * 70}")
            print(f"  {section}")
            print(f"{'─' * 70}")
            
            # Always show errors and warnings
            for item in errors:
                print(f"  ✗ ERROR: {item['message']}")
                if verbose and item["details"]:
                    if isinstance(item["details"], list):
                        for d in item["details"][:20]:
                            print(f"      {d}")
                        if len(item["details"]) > 20:
                            print(f"      ... and {len(item['details'])-20} more")
                    else:
                        print(f"      {item['details']}")
            
            for item in warnings:
                print(f"  ⚠ WARNING: {item['message']}")
                if verbose and item["details"]:
                    if isinstance(item["details"], list):
                        for d in item["details"][:20]:
                            print(f"      {d}")
                        if len(item["details"]) > 20:
                            print(f"      ... and {len(item['details'])-20} more")
                    else:
                        print(f"      {item['details']}")
            
            if verbose:
                for item in infos:
                    print(f"  ✓ {item['message']}")
            elif infos:
                print(f"  ✓ {len(infos)} checks passed")
        
        print(f"\n{'=' * 70}")
        print(f"TOTALS: {self.error_count} errors, {self.warning_count} warnings, {self.info_count} passed")
        print(f"{'=' * 70}")
    
    def to_dict(self):
        return {
            "errors": self.error_count,
            "warnings": self.warning_count,
            "passed": self.info_count,
            "sections": self.sections
        }


def audit_structural(conn, report, verbose):
    """Check required fields and valid values."""
    c = conn.cursor()
    section = "1. STRUCTURAL INTEGRITY"
    
    # Models with missing required fields
    c.execute("SELECT id, name, title, faction FROM models WHERE name IS NULL OR name = ''")
    bad = c.fetchall()
    if bad:
        report.error(section, f"{len(bad)} models with missing name", [str(r) for r in bad])
    else:
        report.info(section, "All models have names")
    
    c.execute("SELECT id, name, faction FROM models WHERE faction IS NULL OR faction = ''")
    bad = c.fetchall()
    if bad:
        report.error(section, f"{len(bad)} models with missing faction", [str(r) for r in bad])
    else:
        report.info(section, "All models have factions")
    
    # Invalid faction values
    c.execute("SELECT DISTINCT faction FROM models")
    factions = {r[0] for r in c.fetchall()}
    invalid = factions - VALID_FACTIONS
    if invalid:
        report.error(section, f"Invalid faction values: {invalid}")
    else:
        report.info(section, f"All factions valid ({len(factions)} unique)")
    
    # Invalid station values
    c.execute("SELECT DISTINCT station FROM models")
    stations = {r[0] for r in c.fetchall()}
    invalid = stations - VALID_STATIONS
    if invalid:
        report.warn(section, f"Unusual station values: {invalid}")
    else:
        report.info(section, f"All stations valid ({len(stations - {None})} unique)")
    
    # Invalid base sizes
    c.execute("SELECT DISTINCT base_size FROM models")
    sizes = {r[0] for r in c.fetchall()}
    invalid = sizes - VALID_BASE_SIZES
    if invalid:
        report.warn(section, f"Unusual base sizes: {invalid}")
    else:
        report.info(section, f"All base sizes valid")
    
    # Models with zero stats (likely extraction failures, exclude verified)
    c.execute("""SELECT id, name, title, df, wp, sz, sp, health FROM models 
                 WHERE (df=0 OR wp=0 OR health=0) AND COALESCE(parse_status,'') != 'verified'""")
    bad = c.fetchall()
    if bad:
        report.error(section, f"{len(bad)} models with zero stats (likely extraction error)",
                     [f"id={r[0]} {r[1]} ({r[2]}): df={r[3]} wp={r[4]} sz={r[5]} sp={r[6]} hp={r[7]}" for r in bad])
    else:
        report.info(section, "No models with zero stats")
    
    # Actions with invalid categories
    c.execute("SELECT DISTINCT category FROM actions")
    cats = {r[0] for r in c.fetchall()}
    invalid = cats - VALID_CATEGORIES
    if invalid:
        report.warn(section, f"Invalid action categories: {invalid}")
    else:
        report.info(section, "All action categories valid")
    
    # Actions with invalid action_types
    c.execute("SELECT DISTINCT action_type FROM actions WHERE category='attack_actions'")
    types = {r[0] for r in c.fetchall()}
    invalid = types - VALID_ACTION_TYPES
    if invalid:
        report.warn(section, f"Invalid attack action types: {invalid}")
    else:
        report.info(section, "All attack action types valid")
    
    # Triggers with invalid timing
    c.execute("SELECT DISTINCT timing FROM triggers")
    timings = {r[0] for r in c.fetchall()}
    invalid = timings - VALID_TIMINGS
    if invalid:
        report.warn(section, f"Invalid trigger timings: {invalid}")
    else:
        report.info(section, "All trigger timings valid")


def audit_statistical(conn, report, verbose):
    """Find statistical outliers that may indicate hallucination."""
    c = conn.cursor()
    section = "2. STATISTICAL OUTLIERS"
    
    for stat, (lo, hi) in STAT_RANGES.items():
        c.execute(f"""SELECT id, name, title, {stat} FROM models 
                     WHERE ({stat} < ? OR {stat} > ?) 
                     AND COALESCE(parse_status,'') != 'verified'""", (lo, hi))
        outliers = c.fetchall()
        if outliers:
            report.warn(section, f"{len(outliers)} models with {stat} outside [{lo},{hi}]",
                       [f"id={r[0]} {r[1]} ({r[2]}): {stat}={r[3]}" for r in outliers])
        else:
            report.info(section, f"All {stat} values in range [{lo},{hi}]")
    
    # Models with unusually high soulstone cache
    c.execute("SELECT id, name, title, soulstone_cache FROM models WHERE soulstone_cache > 4")
    outliers = c.fetchall()
    if outliers:
        report.warn(section, f"{len(outliers)} models with soulstone_cache > 4",
                   [f"id={r[0]} {r[1]} ({r[2]}): cache={r[3]}" for r in outliers])
    else:
        report.info(section, "All soulstone caches reasonable")
    
    # Cost validation (exclude Effigy totems which legitimately have cost=2)
    c.execute("""SELECT id, name, title, station, cost FROM models 
                 WHERE station IN ('Master', 'Totem') AND cost != '-' AND cost IS NOT NULL
                 AND id NOT IN (
                     SELECT model_id FROM model_characteristics WHERE characteristic = 'Effigy'
                 )""")
    bad = c.fetchall()
    if bad:
        report.warn(section, f"{len(bad)} Masters/Totems with non-dash cost",
                   [f"id={r[0]} {r[1]} ({r[2]}): station={r[3]} cost={r[4]}" for r in bad])
    else:
        report.info(section, "All Masters/Totems have '-' cost")
    
    # Models with no abilities AND no actions (suspicious)
    c.execute("""SELECT m.id, m.name, m.title FROM models m
                 WHERE NOT EXISTS (SELECT 1 FROM abilities WHERE model_id=m.id)
                 AND NOT EXISTS (SELECT 1 FROM actions WHERE model_id=m.id)""")
    empty = c.fetchall()
    if empty:
        report.warn(section, f"{len(empty)} models with no abilities and no actions",
                   [f"id={r[0]} {r[1]} ({r[2]})" for r in empty])
    else:
        report.info(section, "All models have at least one ability or action")
    
    # Attack actions with no damage (legitimate: lures, pushes, control effects)
    c.execute("""SELECT a.id, a.name, m.name, m.title FROM actions a
                 JOIN models m ON a.model_id=m.id
                 WHERE a.category='attack_actions' AND (a.damage IS NULL OR a.damage = '')""")
    no_dmg = c.fetchall()
    if no_dmg:
        report.info(section, f"{len(no_dmg)} attack actions with no damage (control effects)")
    else:
        report.info(section, "All attack actions have damage values")
    
    # Tactical actions with damage (shouldn't happen often, damage='0' is effectively none)
    c.execute("""SELECT a.id, a.name, m.name, a.damage FROM actions a
                 JOIN models m ON a.model_id=m.id
                 WHERE a.category='tactical_actions' 
                 AND a.damage IS NOT NULL AND a.damage != '' AND a.damage != '0'""")
    tac_dmg = c.fetchall()
    if tac_dmg:
        report.warn(section, f"{len(tac_dmg)} tactical actions with damage (unusual)",
                   [f"'{r[1]}' on {r[2]}: dmg={r[3]}" for r in tac_dmg])
    else:
        report.info(section, "No tactical actions have damage (correct)")


def audit_consistency(conn, report, verbose):
    """Check cross-table consistency."""
    c = conn.cursor()
    section = "3. CONSISTENCY"
    
    # Faction distribution
    c.execute("SELECT faction, COUNT(*) FROM models GROUP BY faction ORDER BY COUNT(*) DESC")
    dist = c.fetchall()
    report.info(section, "Faction distribution: " + 
                ", ".join(f"{f}: {n}" for f, n in dist))
    
    # Station distribution
    c.execute("SELECT station, COUNT(*) FROM models GROUP BY station ORDER BY COUNT(*) DESC")
    dist = c.fetchall()
    report.info(section, "Station distribution: " + 
                ", ".join(f"{s or 'NULL'}: {n}" for s, n in dist))
    
    # Models with keywords (Versatile models legitimately have no keywords)
    c.execute("""SELECT m.id, m.name, m.title, m.faction FROM models m
                 WHERE m.id NOT IN (SELECT model_id FROM model_keywords)
                 AND m.id NOT IN (
                     SELECT model_id FROM model_characteristics 
                     WHERE characteristic = 'Versatile'
                 )""")
    no_kw = c.fetchall()
    # Also count Versatile models with no keywords for info
    c.execute("""SELECT COUNT(*) FROM models m
                 WHERE m.id NOT IN (SELECT model_id FROM model_keywords)
                 AND m.id IN (
                     SELECT model_id FROM model_characteristics 
                     WHERE characteristic = 'Versatile'
                 )""")
    versatile_no_kw = c.fetchone()[0]
    if versatile_no_kw > 0:
        report.info(section, f"{versatile_no_kw} Versatile models with no keywords (correct)")
    if no_kw:
        report.warn(section, f"{len(no_kw)} non-Versatile models have no keywords assigned",
                   [f"id={r[0]} {r[1]} ({r[2]}) [{r[3]}]" for r in no_kw])
    else:
        report.info(section, "All models have at least one keyword")
    
    # Models with characteristics
    c.execute("SELECT COUNT(*) FROM models")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT model_id) FROM model_characteristics")
    with_char = c.fetchone()[0]
    no_char = total - with_char
    if no_char > 0:
        report.warn(section, f"{no_char} models have no characteristics",
                   None)
    else:
        report.info(section, "All models have at least one characteristic")
    
    # Verify model_factions matches models.faction (one entry per model)
    try:
        c.execute("""SELECT m.id, m.name, m.title, COUNT(mf.faction) as fc
                     FROM models m JOIN model_factions mf ON m.id=mf.model_id
                     GROUP BY m.id HAVING fc > 1""")
        multi = c.fetchall()
        if multi:
            report.error(section, f"{len(multi)} models with multiple faction entries (should be 1 each)",
                        [f"id={r[0]} {r[1]} ({r[2]}): {r[3]} factions" for r in multi])
        else:
            report.info(section, "All models have exactly one faction entry")
    except:
        pass  # Table might not exist
    
    # Masters should have crew_card_name
    c.execute("""SELECT id, name, title, crew_card_name FROM models 
                 WHERE station='Master' AND (crew_card_name IS NULL OR crew_card_name = '')""")
    no_crew = c.fetchall()
    if no_crew:
        report.warn(section, f"{len(no_crew)} Masters with no crew_card_name",
                   [f"id={r[0]} {r[1]} ({r[2]})" for r in no_crew])
    else:
        report.info(section, "All Masters have crew_card_name set")
    
    # Masters should have totem (totem='-' means intentionally no totem)
    c.execute("""SELECT id, name, title, totem FROM models 
                 WHERE station='Master' AND (totem IS NULL OR totem = '')""")
    no_totem = c.fetchall()
    if no_totem:
        report.warn(section, f"{len(no_totem)} Masters with no totem",
                   [f"id={r[0]} {r[1]} ({r[2]})" for r in no_totem])
    else:
        report.info(section, "All Masters have totem set")
    
    # Trigger count per action (more than 5 is suspicious — 5 is legitimate in M4E)
    c.execute("""SELECT a.name, m.name, COUNT(t.id) as tc
                 FROM actions a 
                 JOIN models m ON a.model_id=m.id
                 JOIN triggers t ON t.action_id=a.id
                 GROUP BY a.id HAVING tc > 5
                 ORDER BY tc DESC""")
    many_trig = c.fetchall()
    if many_trig:
        report.warn(section, f"{len(many_trig)} actions with >5 triggers (check for duplicates)",
                   [f"'{r[0]}' on {r[1]}: {r[2]} triggers" for r in many_trig])
    else:
        report.info(section, "No actions have excessive triggers (>5)")


def audit_completeness(conn, report, verbose):
    """Check source PDF coverage."""
    section = "4. COMPLETENESS"
    
    if not SOURCE_DIR.exists():
        report.warn(section, f"Source directory {SOURCE_DIR} not found, skipping coverage check")
        return
    
    # Count source PDFs by type
    stat_pdfs = set()
    crew_pdfs = set()
    upgrade_pdfs = set()
    
    for faction_dir in SOURCE_DIR.iterdir():
        if not faction_dir.is_dir():
            continue
        for keyword_dir in faction_dir.iterdir():
            if not keyword_dir.is_dir():
                continue
            for pdf in keyword_dir.glob("*.pdf"):
                name = pdf.name
                if "Stat" in name:
                    stat_pdfs.add(str(pdf))
                elif "Crew" in name:
                    crew_pdfs.add(str(pdf))
                elif "Upgrade" in name:
                    upgrade_pdfs.add(str(pdf))
    
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM models")
    model_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM crew_cards")
    crew_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM upgrades")
    upgrade_count = c.fetchone()[0]
    
    report.info(section, f"Source PDFs: {len(stat_pdfs)} stat, {len(crew_pdfs)} crew, {len(upgrade_pdfs)} upgrade")
    report.info(section, f"DB records:  {model_count} models, {crew_count} crew cards, {upgrade_count} upgrades")
    
    # Note: stat PDFs include variants (A/B/C) which are different sculpts of same model
    # so stat PDF count won't match model count


def audit_duplicates(conn, report, verbose):
    """Check for remaining duplicate entries."""
    c = conn.cursor()
    section = "5. DUPLICATES"
    
    # Exact name+title duplicates within same faction
    c.execute("""SELECT name, title, faction, COUNT(*) as cnt
                 FROM models GROUP BY name, title, faction
                 HAVING cnt > 1 ORDER BY cnt DESC""")
    dupes = c.fetchall()
    if dupes:
        report.error(section, f"{len(dupes)} exact duplicates (same name+title+faction)",
                    [f"{r[0]} ({r[1]}) [{r[2]}]: {r[3]}x" for r in dupes])
    else:
        report.info(section, "No exact duplicates found")
    
    # Same name, different casing
    c.execute("""SELECT a.id, a.name, a.title, b.id, b.name, b.title
                 FROM models a, models b
                 WHERE a.id < b.id 
                 AND LOWER(a.name) = LOWER(b.name)
                 AND (a.title IS NULL AND b.title IS NULL 
                      OR LOWER(a.title) = LOWER(b.title))""")
    case_dupes = c.fetchall()
    if case_dupes:
        report.warn(section, f"{len(case_dupes)} potential casing duplicates",
                   [f"id={r[0]} '{r[1]}' ({r[2]}) vs id={r[3]} '{r[4]}' ({r[5]})" for r in case_dupes])
    else:
        report.info(section, "No casing duplicates found")
    
    # Duplicate upgrade names
    c.execute("""SELECT name, COUNT(*) FROM upgrades GROUP BY name HAVING COUNT(*) > 1""")
    dup_upgrades = c.fetchall()
    if dup_upgrades:
        report.error(section, f"{len(dup_upgrades)} duplicate upgrade names",
                    [f"{r[0]}: {r[1]}x" for r in dup_upgrades])
    else:
        report.info(section, "No duplicate upgrades")
    
    # Duplicate crew card names
    c.execute("""SELECT name, COUNT(*) FROM crew_cards GROUP BY name HAVING COUNT(*) > 1""")
    dup_crew = c.fetchall()
    if dup_crew:
        report.error(section, f"{len(dup_crew)} duplicate crew card names",
                    [f"{r[0]}: {r[1]}x" for r in dup_crew])
    else:
        report.info(section, "No duplicate crew cards")


def audit_upgrades(conn, report, verbose):
    """Check upgrade card structure."""
    c = conn.cursor()
    section = "6. UPGRADE CARDS"
    
    c.execute("SELECT COUNT(*) FROM upgrades")
    total = c.fetchone()[0]
    report.info(section, f"{total} upgrade cards in database")
    
    # Upgrades with no abilities, actions, or granted triggers
    c.execute("""SELECT u.id, u.name FROM upgrades u
                 WHERE NOT EXISTS (SELECT 1 FROM upgrade_abilities WHERE upgrade_id=u.id)
                 AND NOT EXISTS (SELECT 1 FROM upgrade_actions WHERE upgrade_id=u.id)
                 AND NOT EXISTS (SELECT 1 FROM upgrade_universal_triggers WHERE upgrade_id=u.id)""")
    empty = c.fetchall()
    if empty:
        report.error(section, f"{len(empty)} upgrades with no abilities, actions, or granted triggers",
                    [f"id={r[0]} {r[1]}" for r in empty])
    else:
        report.info(section, "All upgrades have at least one ability, action, or granted trigger")
    
    # Granted triggers count
    try:
        c.execute("SELECT COUNT(*) FROM upgrade_universal_triggers")
        gt = c.fetchone()[0]
        if gt > 0:
            report.info(section, f"{gt} upgrade granted triggers in database")
    except:
        pass
    
    # Upgrade type distribution
    c.execute("SELECT upgrade_type, COUNT(*) FROM upgrades GROUP BY upgrade_type ORDER BY COUNT(*) DESC")
    dist = c.fetchall()
    report.info(section, "Type distribution: " + 
                ", ".join(f"{t or 'NULL'}: {n}" for t, n in dist))
    
    # Faction distribution
    c.execute("SELECT faction, COUNT(*) FROM upgrades GROUP BY faction ORDER BY COUNT(*) DESC")
    dist = c.fetchall()
    report.info(section, "Faction distribution: " + 
                ", ".join(f"{f}: {n}" for f, n in dist))


def audit_cross_table(conn, report, verbose):
    """Check cross-table references."""
    c = conn.cursor()
    section = "7. CROSS-TABLE REFERENCES"
    
    # Crew cards referencing masters that exist (some crew cards reference Henchmen)
    c.execute("""SELECT cc.name, cc.associated_master, cc.associated_title
                 FROM crew_cards cc
                 WHERE NOT EXISTS (
                     SELECT 1 FROM models m 
                     WHERE m.name = cc.associated_master 
                     AND m.station IN ('Master', 'Henchman')
                 )""")
    orphan_crew = c.fetchall()
    if orphan_crew:
        report.warn(section, f"{len(orphan_crew)} crew cards reference non-existent masters",
                   [f"'{r[0]}' -> master '{r[1]}' ({r[2]})" for r in orphan_crew])
    else:
        report.info(section, "All crew cards reference existing masters")
    
    # Actions with triggers that have no suit
    c.execute("""SELECT t.name, a.name, m.name FROM triggers t
                 JOIN actions a ON t.action_id=a.id
                 JOIN models m ON a.model_id=m.id
                 WHERE t.suit IS NULL OR t.suit = ''""")
    no_suit = c.fetchall()
    if no_suit:
        report.warn(section, f"{len(no_suit)} triggers with no suit specified",
                   [f"trigger '{r[0]}' on action '{r[1]}' ({r[2]})" for r in no_suit])
    else:
        report.info(section, "All triggers have suits specified")
    
    # Average abilities/actions per model
    c.execute("SELECT AVG(cnt) FROM (SELECT COUNT(*) as cnt FROM abilities GROUP BY model_id)")
    avg_ab = c.fetchone()[0] or 0
    c.execute("SELECT AVG(cnt) FROM (SELECT COUNT(*) as cnt FROM actions GROUP BY model_id)")
    avg_act = c.fetchone()[0] or 0
    report.info(section, f"Averages per model: {avg_ab:.1f} abilities, {avg_act:.1f} actions")


def main():
    parser = argparse.ArgumentParser(description="M4E Database Final Audit")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show all details")
    parser.add_argument("--export", help="Export report to JSON file")
    args = parser.parse_args()
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    
    report = AuditReport()
    
    audit_structural(conn, report, args.verbose)
    audit_statistical(conn, report, args.verbose)
    audit_consistency(conn, report, args.verbose)
    audit_completeness(conn, report, args.verbose)
    audit_duplicates(conn, report, args.verbose)
    audit_upgrades(conn, report, args.verbose)
    audit_cross_table(conn, report, args.verbose)
    
    report.print_report(args.verbose)
    
    if args.export:
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2)
        print(f"\nExported to {args.export}")
    
    conn.close()
    return 0 if report.error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
