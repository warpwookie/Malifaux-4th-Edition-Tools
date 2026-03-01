#!/usr/bin/env python3
"""
pdf_text_batch.py — Batch re-ingestion and validation of M4E cards from PDF text layers.

Walks source_pdfs/ directories and processes all stat card PDFs through:
  pdf_text_extractor → merger → validator → db_loader

Also validates DB contents against source PDFs and pipeline_work JSONs.

Usage:
    python scripts/pdf_text_batch.py --faction Guild
    python scripts/pdf_text_batch.py --all
    python scripts/pdf_text_batch.py --all --dry-run
    python scripts/pdf_text_batch.py --all --compare-only
    python scripts/pdf_text_batch.py --reconcile
    python scripts/pdf_text_batch.py --compare-all
    python scripts/pdf_text_batch.py --compare-all --export-diffs report.json
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


# ── PDF Discovery ──────────────────────────────────────────────────────

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


def discover_all_pdfs():
    """
    Walk source_pdfs/ to find ALL card PDFs (stat, crew, upgrade).

    Returns dict with keys 'stat', 'crew', 'upgrade', each a list of
    (pdf_path, faction_name, keyword_name).
    """
    result = {"stat": [], "crew": [], "upgrade": []}

    for f_name in FACTIONS:
        faction_dir = SOURCE_DIR / f_name
        if not faction_dir.exists():
            continue

        for keyword_dir in sorted(faction_dir.iterdir()):
            if not keyword_dir.is_dir():
                continue
            keyword = keyword_dir.name

            for pdf_file in sorted(keyword_dir.glob("M4E_*.pdf")):
                name = pdf_file.stem

                # Skip alt-art variants
                if re.search(r'_[B-Z]$', name):
                    continue

                if name.startswith("M4E_Stat_"):
                    result["stat"].append((pdf_file, f_name, keyword))
                elif name.startswith("M4E_Crew_"):
                    result["crew"].append((pdf_file, f_name, keyword))
                elif name.startswith("M4E_Upgrade_"):
                    result["upgrade"].append((pdf_file, f_name, keyword))

    return result


# ── Single Card Processing ─────────────────────────────────────────────

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


# ── Deep Comparison ────────────────────────────────────────────────────

def _normalize_text(text):
    """Normalize text for comparison: strip whitespace, collapse spaces."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', str(text).strip())


def _vals_equivalent(db_val, pdf_val):
    """Check if two values are semantically equivalent.

    Handles: None vs '-', None vs '', case differences.
    """
    # Both None/empty
    if not db_val and not pdf_val:
        return True
    # None vs dash (tactical actions have '-' for damage in PDF, NULL in DB)
    if db_val is None and str(pdf_val) == "-":
        return True
    if pdf_val is None and str(db_val) == "-":
        return True
    # String comparison
    return str(db_val).strip() == str(pdf_val).strip()


def compare_with_db(pdf_path, faction, keyword, conn):
    """
    Extract card data from PDF and deep-compare against DB values.

    Compares: stats, abilities, actions, triggers, keywords, characteristics.
    Returns dict with structured diffs.
    """
    result = {
        "pdf": str(pdf_path.name),
        "faction": faction,
        "keyword": keyword,
        "diffs": [],
        "categories": {},  # Track which categories matched/differed
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

        # Look up existing DB record — try multiple matching strategies
        c = conn.cursor()

        # Strategy 1: Exact name + title
        if title:
            c.execute(
                "SELECT * FROM models WHERE name COLLATE NOCASE=? AND title COLLATE NOCASE=?",
                (name, title))
        else:
            c.execute(
                "SELECT * FROM models WHERE name COLLATE NOCASE=? AND title IS NULL",
                (name,))
        row = c.fetchone()

        # Strategy 2: With faction qualifier
        if not row:
            if title:
                c.execute(
                    "SELECT * FROM models WHERE name COLLATE NOCASE=? AND title COLLATE NOCASE=? AND faction=?",
                    (name, title, faction))
            else:
                c.execute(
                    "SELECT * FROM models WHERE name COLLATE NOCASE=? AND title IS NULL AND faction=?",
                    (name, faction))
            row = c.fetchone()

        # Strategy 3: Fuzzy name match (handle quotes, apostrophes, special chars)
        if not row:
            c.execute("SELECT * FROM models WHERE faction=?", (faction,))
            candidates = c.fetchall()
            # Normalize for matching: strip quotes, replace smart quotes, etc.
            def _norm(s):
                if not s:
                    return ""
                s = s.replace("\u2018", "'").replace("\u2019", "'")
                s = s.replace("\u201c", '"').replace("\u201d", '"')
                s = s.replace('"', '').replace("'", "").lower().strip()
                return s

            norm_name = _norm(name)
            norm_title = _norm(title) if title else None
            for cand in candidates:
                if _norm(cand["name"]) == norm_name:
                    if norm_title is None and cand["title"] is None:
                        row = cand
                        break
                    elif norm_title and cand["title"] and _norm(cand["title"]) == norm_title:
                        row = cand
                        break

        if not row:
            result["diffs"].append("NOT_IN_DB")
            return result

        db_id = row["id"]

        # Dual-title masters: the PDF text extractor may extract actions from
        # both front (shared) and back (title-specific), while the DB stores
        # each title's content separately. Skip count-based comparisons for
        # these masters; only compare matching action/ability details.
        is_dual_title_master = (
            row["station"] == "Master" and row["title"] and
            c.execute(
                "SELECT COUNT(*) FROM models WHERE name COLLATE NOCASE=? AND id != ?",
                (name, db_id)
            ).fetchone()[0] > 0
        )

        # ── 1. Stats comparison ──
        stat_fields = {
            "df": merged.get("df"),
            "wp": merged.get("wp"),
            "sz": merged.get("sz"),
            "sp": merged.get("sp"),
            "health": merged.get("health"),
            "cost": merged.get("cost"),
            "station": merged.get("station"),
            "base_size": merged.get("base_size"),
        }

        stats_ok = True
        for field, new_val in stat_fields.items():
            db_val = row[field]
            if new_val is not None and str(new_val) != str(db_val):
                result["diffs"].append(f"STAT {field}: DB={db_val} PDF={new_val}")
                stats_ok = False
        result["categories"]["stats"] = "match" if stats_ok else "diff"

        # ── 2. Keywords comparison ──
        db_keywords = {
            r["keyword"] for r in c.execute(
                "SELECT keyword FROM model_keywords WHERE model_id=?", (db_id,)
            ).fetchall()
        }
        pdf_keywords = set(merged.get("keywords", []))
        if db_keywords != pdf_keywords:
            added = pdf_keywords - db_keywords
            removed = db_keywords - pdf_keywords
            if added:
                result["diffs"].append(f"KEYWORD +PDF: {added}")
            if removed:
                result["diffs"].append(f"KEYWORD +DB: {removed}")
        result["categories"]["keywords"] = "match" if db_keywords == pdf_keywords else "diff"

        # ── 3. Characteristics comparison ──
        db_chars = {
            r["characteristic"] for r in c.execute(
                "SELECT characteristic FROM model_characteristics WHERE model_id=?", (db_id,)
            ).fetchall()
        }
        # Extract characteristics from merged (may include station info)
        pdf_chars = set()
        for ch in merged.get("characteristics", []):
            pdf_chars.add(ch)
        if db_chars != pdf_chars:
            added = pdf_chars - db_chars
            removed = db_chars - pdf_chars
            if added:
                result["diffs"].append(f"CHAR +PDF: {added}")
            if removed:
                result["diffs"].append(f"CHAR +DB: {removed}")
        result["categories"]["characteristics"] = "match" if db_chars == pdf_chars else "diff"

        # ── 4. Abilities comparison ──
        db_abilities = c.execute(
            "SELECT name, text FROM abilities WHERE model_id=? ORDER BY name COLLATE NOCASE",
            (db_id,)
        ).fetchall()
        db_ability_names = {r["name"] for r in db_abilities}
        pdf_abilities = merged.get("abilities", [])
        pdf_ability_names = {a["name"] for a in pdf_abilities}

        abilities_ok = True
        if not is_dual_title_master:
            if len(db_abilities) != len(pdf_abilities):
                result["diffs"].append(
                    f"ABILITY count: DB={len(db_abilities)} PDF={len(pdf_abilities)}")
                abilities_ok = False

            name_diff_added = pdf_ability_names - db_ability_names
            name_diff_removed = db_ability_names - pdf_ability_names
            if name_diff_added:
                result["diffs"].append(f"ABILITY +PDF: {name_diff_added}")
                abilities_ok = False
            if name_diff_removed:
                result["diffs"].append(f"ABILITY +DB: {name_diff_removed}")
                abilities_ok = False
        result["categories"]["abilities"] = "match" if abilities_ok else "diff"

        # ── 5. Actions comparison ──
        db_actions = c.execute(
            "SELECT id, name, category, action_type, range, skill_value, resist, damage "
            "FROM actions WHERE model_id=? ORDER BY name COLLATE NOCASE",
            (db_id,)
        ).fetchall()
        db_action_names = {r["name"] for r in db_actions}
        pdf_actions = merged.get("actions", [])
        pdf_action_names = {a["name"] for a in pdf_actions}

        actions_ok = True
        if not is_dual_title_master:
            if len(db_actions) != len(pdf_actions):
                result["diffs"].append(
                    f"ACTION count: DB={len(db_actions)} PDF={len(pdf_actions)}")
                actions_ok = False

            name_diff_added = pdf_action_names - db_action_names
            name_diff_removed = db_action_names - pdf_action_names
            if name_diff_added:
                result["diffs"].append(f"ACTION +PDF: {name_diff_added}")
                actions_ok = False
            if name_diff_removed:
                result["diffs"].append(f"ACTION +DB: {name_diff_removed}")
                actions_ok = False

        # Compare action details for matching names
        db_action_map = {r["name"]: dict(r) for r in db_actions}
        for pdf_act in pdf_actions:
            aname = pdf_act["name"]
            if aname in db_action_map:
                db_act = db_action_map[aname]
                for field in ("category", "action_type", "resist", "damage"):
                    pdf_val = pdf_act.get(field)
                    db_val = db_act.get(field)
                    if not _vals_equivalent(db_val, pdf_val):
                        result["diffs"].append(
                            f"ACTION {aname}.{field}: DB={db_val} PDF={pdf_val}")
                        actions_ok = False
        result["categories"]["actions"] = "match" if actions_ok else "diff"

        # ── 6. Triggers comparison ──
        # For dual-title masters, only check triggers on actions that exist
        # in this DB record (skip actions from the shared front that may only
        # be present in the other title variant's record).
        triggers_ok = True
        for pdf_act in pdf_actions:
            aname = pdf_act["name"]
            pdf_triggers = pdf_act.get("triggers", [])
            pdf_trig_names = {t["name"] for t in pdf_triggers}

            # Find matching DB action (skip non-matching for dual-title masters)
            if aname in db_action_map:
                db_act_id = db_action_map[aname]["id"]
                db_triggers = c.execute(
                    "SELECT name, suit, timing FROM triggers WHERE action_id=? ORDER BY name",
                    (db_act_id,)
                ).fetchall()
                db_trig_names = {t["name"] for t in db_triggers}

                if len(db_triggers) != len(pdf_triggers):
                    result["diffs"].append(
                        f"TRIGGER {aname} count: DB={len(db_triggers)} PDF={len(pdf_triggers)}")
                    triggers_ok = False

                trig_added = pdf_trig_names - db_trig_names
                trig_removed = db_trig_names - pdf_trig_names
                if trig_added:
                    result["diffs"].append(f"TRIGGER {aname} +PDF: {trig_added}")
                    triggers_ok = False
                if trig_removed:
                    result["diffs"].append(f"TRIGGER {aname} +DB: {trig_removed}")
                    triggers_ok = False

        result["categories"]["triggers"] = "match" if triggers_ok else "diff"

    except Exception as e:
        result["diffs"].append(f"EXCEPTION: {type(e).__name__}: {e}")

    return result


# ── Coverage Reconciliation ────────────────────────────────────────────

def reconcile_coverage(conn):
    """
    Check that every source PDF has a DB record and vice versa.

    Returns a report dict with findings.
    """
    report = {
        "stat": {"total_pdfs": 0, "matched": 0, "skipped_alt": 0, "missing_from_db": [], "errors": []},
        "crew": {"total_pdfs": 0, "matched": 0, "skipped_alt": 0, "missing_from_db": [], "errors": []},
        "upgrade": {"total_pdfs": 0, "matched": 0, "skipped_alt": 0, "missing_from_db": [], "errors": []},
        "orphan_db_records": [],
        "missing_source_files": [],
    }

    c = conn.cursor()
    all_pdfs = discover_all_pdfs()

    # ── Check stat card PDFs → DB ──
    for pdf_path, faction, keyword in all_pdfs["stat"]:
        report["stat"]["total_pdfs"] += 1
        pdf_str = str(pdf_path)

        # Check if source_pdf matches (use LIKE for path variations)
        row = c.execute(
            "SELECT id, name FROM models WHERE source_pdf LIKE ?",
            (f"%{pdf_path.name}%",)
        ).fetchone()

        if row:
            report["stat"]["matched"] += 1
        else:
            report["stat"]["missing_from_db"].append(
                f"{faction}/{keyword}/{pdf_path.name}")

    # ── Check crew card PDFs → DB ──
    for pdf_path, faction, keyword in all_pdfs["crew"]:
        report["crew"]["total_pdfs"] += 1

        row = c.execute(
            "SELECT id, name FROM crew_cards WHERE source_pdf LIKE ?",
            (f"%{pdf_path.name}%",)
        ).fetchone()

        if row:
            report["crew"]["matched"] += 1
        else:
            report["crew"]["missing_from_db"].append(
                f"{faction}/{keyword}/{pdf_path.name}")

    # ── Check upgrade PDFs → DB ──
    for pdf_path, faction, keyword in all_pdfs["upgrade"]:
        report["upgrade"]["total_pdfs"] += 1

        row = c.execute(
            "SELECT id, name FROM upgrades WHERE source_pdf LIKE ?",
            (f"%{pdf_path.name}%",)
        ).fetchone()

        if row:
            report["upgrade"]["matched"] += 1
        else:
            report["upgrade"]["missing_from_db"].append(
                f"{faction}/{keyword}/{pdf_path.name}")

    # ── Check DB records → source files ──
    for table, label in [("models", "stat"), ("crew_cards", "crew"), ("upgrades", "upgrade")]:
        rows = c.execute(f"SELECT id, name, source_pdf FROM {table}").fetchall()
        for row in rows:
            src = row["source_pdf"]
            if src and not Path(src).exists():
                report["missing_source_files"].append(
                    f"{label}: {row['name']} (id={row['id']}) → {src}")

    return report


# ── Crew Card Comparison (from pipeline_work JSONs) ────────────────────

def compare_crew_cards_from_json(conn):
    """
    Compare crew card data in DB against pipeline_work merged JSONs.

    Returns list of diff dicts.
    """
    results = []
    c = conn.cursor()

    # Find all crew card merged JSONs
    crew_jsons = list(WORK_DIR.rglob("*Crew*_merged.json"))

    for json_path in sorted(crew_jsons):
        try:
            with open(json_path, encoding="utf-8") as f:
                merged = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            results.append({"json": json_path.name, "diffs": [f"READ_ERROR: {e}"]})
            continue

        if merged.get("card_type") != "crew_card":
            continue

        name = merged.get("name", "?")
        result = {"json": json_path.name, "name": name, "diffs": []}

        # Find in DB
        row = c.execute(
            "SELECT id, name, faction FROM crew_cards WHERE name COLLATE NOCASE=?",
            (name,)
        ).fetchone()

        if not row:
            result["diffs"].append("NOT_IN_DB")
            results.append(result)
            continue

        cc_id = row["id"]

        # Compare tokens
        db_tokens = {
            r["name"]: r["text"] for r in c.execute(
                "SELECT name, text FROM crew_tokens WHERE crew_card_id=?", (cc_id,)
            ).fetchall()
        }
        pdf_tokens = {t["name"]: t.get("text", "") for t in merged.get("tokens", [])}

        # Only flag tokens in JSON that are MISSING from DB.
        # DB will have additional auto-discovered tokens (db_loader regex scan) — expected.
        missing_from_db = set(pdf_tokens.keys()) - set(db_tokens.keys())
        if missing_from_db:
            result["diffs"].append(f"TOKEN +JSON (missing from DB): {missing_from_db}")

        # Compare keyword abilities
        db_abilities = {
            r["name"] for r in c.execute(
                "SELECT name FROM crew_keyword_abilities WHERE crew_card_id=?", (cc_id,)
            ).fetchall()
        }
        pdf_abilities = set()
        for section in merged.get("keyword_abilities", []):
            if isinstance(section, dict):
                pdf_abilities.add(section.get("name", ""))
            elif isinstance(section, list):
                for a in section:
                    if isinstance(a, dict):
                        pdf_abilities.add(a.get("name", ""))

        # Also check top-level abilities key used by some extractors
        for a in merged.get("abilities", []):
            if isinstance(a, dict):
                pdf_abilities.add(a.get("name", ""))

        pdf_abilities.discard("")
        if db_abilities and pdf_abilities and db_abilities != pdf_abilities:
            added = pdf_abilities - db_abilities
            removed = db_abilities - pdf_abilities
            if added:
                result["diffs"].append(f"CREW_ABILITY +JSON: {added}")
            if removed:
                result["diffs"].append(f"CREW_ABILITY +DB: {removed}")

        # Compare keyword actions
        db_actions = {
            r["name"] for r in c.execute(
                "SELECT name FROM crew_keyword_actions WHERE crew_card_id=?", (cc_id,)
            ).fetchall()
        }
        pdf_actions = set()
        for section in merged.get("keyword_actions", []):
            if isinstance(section, dict):
                pdf_actions.add(section.get("name", ""))
            elif isinstance(section, list):
                for a in section:
                    if isinstance(a, dict):
                        pdf_actions.add(a.get("name", ""))

        for a in merged.get("actions", []):
            if isinstance(a, dict):
                pdf_actions.add(a.get("name", ""))

        pdf_actions.discard("")
        if db_actions and pdf_actions and db_actions != pdf_actions:
            added = pdf_actions - db_actions
            removed = db_actions - pdf_actions
            if added:
                result["diffs"].append(f"CREW_ACTION +JSON: {added}")
            if removed:
                result["diffs"].append(f"CREW_ACTION +DB: {removed}")

        # Compare markers
        db_markers = {
            r["name"] for r in c.execute(
                "SELECT name FROM crew_markers WHERE crew_card_id=?", (cc_id,)
            ).fetchall()
        }
        pdf_markers = {m.get("name", "") for m in merged.get("markers", []) if isinstance(m, dict)}
        pdf_markers.discard("")
        if db_markers and pdf_markers and db_markers != pdf_markers:
            added = pdf_markers - db_markers
            removed = db_markers - pdf_markers
            if added:
                result["diffs"].append(f"MARKER +JSON: {added}")
            if removed:
                result["diffs"].append(f"MARKER +DB: {removed}")

        if result["diffs"]:
            results.append(result)

    return results, len(crew_jsons)


# ── Upgrade Comparison (from pipeline_work JSONs) ──────────────────────

def compare_upgrades_from_json(conn):
    """
    Compare upgrade data in DB against pipeline_work merged JSONs.

    Returns list of diff dicts.
    """
    results = []
    c = conn.cursor()

    upgrade_jsons = list(WORK_DIR.rglob("*Upgrade*_merged.json"))

    for json_path in sorted(upgrade_jsons):
        try:
            with open(json_path, encoding="utf-8") as f:
                merged = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            results.append({"json": json_path.name, "diffs": [f"READ_ERROR: {e}"]})
            continue

        if merged.get("card_type") != "upgrade":
            continue

        name = merged.get("name", "?")
        result = {"json": json_path.name, "name": name, "diffs": []}

        row = c.execute(
            "SELECT id, name FROM upgrades WHERE name COLLATE NOCASE=?",
            (name,)
        ).fetchone()

        if not row:
            result["diffs"].append("NOT_IN_DB")
            results.append(result)
            continue

        uid = row["id"]

        # Compare abilities
        db_abilities = {
            r["name"] for r in c.execute(
                "SELECT name FROM upgrade_abilities WHERE upgrade_id=?", (uid,)
            ).fetchall()
        }
        pdf_abilities = {a.get("name", "") for a in merged.get("abilities", []) if isinstance(a, dict)}
        pdf_abilities.discard("")

        if db_abilities and pdf_abilities and db_abilities != pdf_abilities:
            added = pdf_abilities - db_abilities
            removed = db_abilities - pdf_abilities
            if added:
                result["diffs"].append(f"UPG_ABILITY +JSON: {added}")
            if removed:
                result["diffs"].append(f"UPG_ABILITY +DB: {removed}")

        # Compare actions
        db_actions = {
            r["name"] for r in c.execute(
                "SELECT name FROM upgrade_actions WHERE upgrade_id=?", (uid,)
            ).fetchall()
        }
        pdf_actions = {a.get("name", "") for a in merged.get("actions", []) if isinstance(a, dict)}
        pdf_actions.discard("")

        if db_actions and pdf_actions and db_actions != pdf_actions:
            added = pdf_actions - db_actions
            removed = db_actions - pdf_actions
            if added:
                result["diffs"].append(f"UPG_ACTION +JSON: {added}")
            if removed:
                result["diffs"].append(f"UPG_ACTION +DB: {removed}")

        if result["diffs"]:
            results.append(result)

    return results, len(upgrade_jsons)


# ── Report Printing ────────────────────────────────────────────────────

def print_reconcile_report(report):
    """Print the coverage reconciliation report."""
    print(f"\n{'─' * 70}")
    print("  COVERAGE RECONCILIATION")
    print(f"{'─' * 70}")

    for card_type, label in [("stat", "Stat cards"), ("crew", "Crew cards"), ("upgrade", "Upgrades")]:
        r = report[card_type]
        total = r["total_pdfs"]
        matched = r["matched"]
        missing = len(r["missing_from_db"])
        pct = (matched / total * 100) if total > 0 else 0
        print(f"  {label}: {total} PDFs, {matched} matched ({pct:.0f}%), {missing} missing from DB")

        if r["missing_from_db"]:
            for m in r["missing_from_db"][:10]:
                print(f"    - {m}")
            if len(r["missing_from_db"]) > 10:
                print(f"    ... and {len(r['missing_from_db']) - 10} more")

    if report["missing_source_files"]:
        print(f"\n  Orphan DB records (source PDF missing): {len(report['missing_source_files'])}")
        for m in report["missing_source_files"][:10]:
            print(f"    - {m}")
    else:
        print(f"\n  Orphan DB records: 0")


def print_compare_summary(results, card_type="stat"):
    """Print summary of deep comparison results."""
    total = len(results)
    with_diffs = [r for r in results if r.get("diffs")]
    clean = total - len(with_diffs)

    print(f"\n{'─' * 70}")
    print(f"  {card_type.upper()} CARD DEEP COMPARISON ({total} cards)")
    print(f"{'─' * 70}")

    if card_type == "stat":
        # Category-level stats
        categories = ["stats", "keywords", "characteristics", "abilities", "actions", "triggers"]
        for cat in categories:
            match_count = sum(
                1 for r in results
                if r.get("categories", {}).get(cat) == "match"
            )
            diff_count = sum(
                1 for r in results
                if r.get("categories", {}).get(cat) == "diff"
            )
            checked = match_count + diff_count
            if checked > 0:
                pct = match_count / checked * 100
                print(f"  {cat:20s}: {match_count}/{checked} match ({pct:.1f}%)")

    print(f"\n  Clean: {clean}/{total}  |  With diffs: {len(with_diffs)}")

    if with_diffs:
        print(f"\n  DIFFS:")
        for r in with_diffs:
            name = r.get("name", r.get("json", "?"))
            print(f"    {name}:")
            for d in r["diffs"]:
                print(f"      - {d}")


# ── Main ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Batch process and validate M4E cards from PDF source")
    parser.add_argument("--faction", help="Process a single faction")
    parser.add_argument("--all", action="store_true", help="Process all factions")
    parser.add_argument("--dry-run", action="store_true",
                        help="Extract + validate only, don't write to DB")
    parser.add_argument("--compare-only", action="store_true",
                        help="Deep-compare stat card extractions against DB")
    parser.add_argument("--reconcile", action="store_true",
                        help="Check PDF ↔ DB coverage (fast, no extraction)")
    parser.add_argument("--compare-crew", action="store_true",
                        help="Compare crew cards via pipeline_work JSONs")
    parser.add_argument("--compare-upgrades", action="store_true",
                        help="Compare upgrades via pipeline_work JSONs")
    parser.add_argument("--compare-all", action="store_true",
                        help="Run all comparison modes")
    parser.add_argument("--export-diffs", type=str,
                        help="Export all diffs to JSON file")
    parser.add_argument("--save-json", action="store_true",
                        help="Save intermediate merged JSON to pipeline_work/")
    parser.add_argument("--db", default=str(DB_PATH),
                        help="Database path (default: db/m4e.db)")
    parser.add_argument("--keyword", help="Filter to a specific keyword folder")
    parser.add_argument("--limit", type=int, help="Process at most N cards")
    args = parser.parse_args()

    # Determine what modes to run
    run_reconcile = args.reconcile or args.compare_all
    run_compare = args.compare_only or args.compare_all
    run_crew = args.compare_crew or args.compare_all
    run_upgrades = args.compare_upgrades or args.compare_all
    run_process = not (run_reconcile or run_compare or run_crew or run_upgrades)

    if run_process and not args.faction and not args.all:
        parser.error("Specify --faction NAME, --all, --reconcile, --compare-all, or other mode")

    # Connect to DB
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    all_diffs = {}
    start = time.time()

    print("=" * 70)
    print("M4E SOURCE VALIDATION")
    print("=" * 70)

    # ── Reconcile ──
    if run_reconcile:
        print("\nRunning coverage reconciliation...")
        report = reconcile_coverage(conn)
        print_reconcile_report(report)
        all_diffs["reconcile"] = report

    # ── Deep stat card comparison ──
    if run_compare:
        faction = args.faction if args.faction else None
        if not args.faction and not args.all and args.compare_all:
            faction = None  # compare-all implies all factions

        pdfs = discover_stat_pdfs(faction=faction)
        if args.keyword:
            pdfs = [(p, f, k) for p, f, k in pdfs if k == args.keyword]
        if args.limit:
            pdfs = pdfs[:args.limit]

        print(f"\nDeep-comparing {len(pdfs)} stat cards against DB...")
        results = []
        for i, (pdf_path, f_name, kw_name) in enumerate(pdfs, 1):
            r = compare_with_db(pdf_path, f_name, kw_name, conn)
            results.append(r)

            if r["diffs"]:
                short = pdf_path.stem.replace("M4E_Stat_", "")
                name = r.get("name", "?")
                print(f"  [{i:3d}/{len(pdfs)}] DIFF {f_name}/{short} ({name}): {len(r['diffs'])} diffs")
            elif i % 50 == 0 or i == len(pdfs):
                elapsed = time.time() - start
                rate = i / elapsed if elapsed > 0 else 0
                ok = sum(1 for r2 in results if not r2.get("diffs"))
                print(f"  [{i:3d}/{len(pdfs)}] ok={ok} ({rate:.1f} cards/sec)")

        print_compare_summary(results, "stat")
        all_diffs["stat_comparison"] = [r for r in results if r.get("diffs")]

    # ── Crew card comparison ──
    if run_crew:
        print("\nComparing crew cards from pipeline_work JSONs...")
        crew_diffs, crew_total = compare_crew_cards_from_json(conn)
        print_compare_summary(
            [{"diffs": []} for _ in range(crew_total - len(crew_diffs))] + crew_diffs,
            "crew"
        )
        all_diffs["crew_comparison"] = crew_diffs

    # ── Upgrade comparison ──
    if run_upgrades:
        print("\nComparing upgrades from pipeline_work JSONs...")
        upg_diffs, upg_total = compare_upgrades_from_json(conn)
        print_compare_summary(
            [{"diffs": []} for _ in range(upg_total - len(upg_diffs))] + upg_diffs,
            "upgrade"
        )
        all_diffs["upgrade_comparison"] = upg_diffs

    # ── Standard processing mode ──
    if run_process:
        faction = args.faction if args.faction else None
        pdfs = discover_stat_pdfs(faction=faction)
        if args.keyword:
            pdfs = [(p, f, k) for p, f, k in pdfs if k == args.keyword]
        if args.limit:
            pdfs = pdfs[:args.limit]

        print(f"\nProcessing {len(pdfs)} stat card PDFs...")

        ok_count = 0
        fail_count = 0
        skip_count = 0

        for i, (pdf_path, f_name, kw_name) in enumerate(pdfs, 1):
            pct = i / len(pdfs) * 100
            short_name = pdf_path.stem.replace("M4E_Stat_", "")

            r = process_one_card(
                pdf_path, f_name, kw_name, conn=conn,
                dry_run=args.dry_run, save_json=args.save_json)

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
                status_icon = {"ok": "+", "dry_run": ".", "validation_fail": "!",
                               "extract_error": "X", "exception": "E"}.get(r["status"], "?")
                print(f"  [{i:3d}/{len(pdfs)}] {pct:5.1f}% {status_icon} {f_name}/{kw_name}/{short_name} ({name})")
                for iss in r["issues"]:
                    print(f"         {iss}")
            elif i % 25 == 0 or i == len(pdfs):
                elapsed = time.time() - start
                rate = i / elapsed if elapsed > 0 else 0
                print(f"  [{i:3d}/{len(pdfs)}] {pct:5.1f}% ok={ok_count} fail={fail_count} ({rate:.1f} cards/sec)")

        if not args.dry_run:
            conn.commit()

        print(f"\n  OK: {ok_count}  Fail: {fail_count}  Skip: {skip_count}")

    # ── Export diffs ──
    if args.export_diffs and all_diffs:
        export_path = Path(args.export_diffs)
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(all_diffs, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nDiffs exported to: {export_path}")

    conn.close()

    elapsed = time.time() - start
    print(f"\n{'=' * 70}")
    print(f"Completed in {elapsed:.1f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
