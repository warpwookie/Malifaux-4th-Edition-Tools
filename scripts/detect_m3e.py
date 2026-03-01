#!/usr/bin/env python3
"""Detect M3E (3rd Edition) contamination in M4E database and JSON exports.

Scans all text fields across all tables for M3E-specific terminology,
stale mechanics, hallucinated rules, and data quality issues.

Run after any data changes or re-extractions:
    python scripts/detect_m3e.py
    python scripts/detect_m3e.py --verbose
    python scripts/detect_m3e.py --export report.json
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "m4e.db"
JSON_DIR = Path(__file__).resolve().parent.parent / "Model Data Json"

# ── M3E-specific terms that should NEVER appear in M4E data ────────────
# Each entry: (regex_pattern, description, severity, context_note)
M3E_HARD_TERMS = [
    # Stations
    (r"\bEnforcer\b", "Enforcer station (M3E only, removed in M4E)", "error",
     "M4E stations: Master, Henchman, Minion, Totem, Peon"),

    # Stats
    (r"\bCa\s*stat\b", "Ca stat (M3E casting stat → M4E uses Skl)", "error", None),
    (r"\bMl\s*stat\b", "Ml stat (M3E melee stat → M4E uses Skl)", "error", None),
    (r"\bSh\s*stat\b", "Sh stat (M3E shooting stat → M4E uses Skl)", "error", None),

    # Factions
    (r"\bdual[\s-]?faction\b", "Dual-faction (doesn't exist in M4E)", "error",
     "All M4E models have exactly one faction"),

    # Mechanics
    (r"\bupgrade\s+slot\b", "Upgrade slot (M3E concept)", "error", None),
    (r"\bhorror\s+duel\b", "Horror duel (M3E concept)", "error", None),
    (r"\breactivat(?:e|ion)\b", "Reactivate/reactivation (removed in M4E)", "error", None),
    (r"\bnegative\s+flip\b", "Negative flip (M3E; M4E uses (-) notation)", "error", None),
    (r"\bpositive\s+flip\b", "Positive flip (M3E; M4E uses (+) notation)", "error", None),

    # Token stacking (M3E had stackable conditions with values)
    (r"\bdamage\s+equal\s+to\s+(?:its\s+)?value\b",
     "Token stacking language (M3E; M4E tokens don't stack)", "error",
     "M4E tokens cannot stack; each model has at most one of each token"),
    (r"\breduces?\s+by\s+1\b.*token",
     "Token value reduction (M3E stacking mechanic)", "warning",
     "Check if this is referencing a value that decreases, not M4E token behavior"),
]

# ── Soft checks: terms that CAN appear legitimately but are suspicious ──
M3E_SOFT_TERMS = [
    # These terms exist in M4E but were reworked; flag for manual review
    (r"\bparalyz(?:ed|e)\b",
     "Paralyzed (M3E condition; M4E uses Stunned. May be a valid trigger name)", "info",
     "Verify against card image — Wyrd reuses some names thematically"),

    # Conditions vs tokens
    (r"\bcondition\b",
     "Condition (M3E term; M4E calls them 'tokens')", "info",
     "False positive if used in plain English sense (e.g., 'if this condition is met')"),

    # Soulstone terminology
    (r"\bsoulstone\s+cache\b",
     "Soulstone cache (verify correct M4E usage)", "info",
     "M4E uses 'soulstone cache' for Masters, but differently than M3E"),
]

# ── Known false positives (legitimate M4E usage of M3E-era term names) ──
FALSE_POSITIVES = {
    "Terrifying",       # M4E ability (reworked mechanic, same name)
    "Manipulative",     # M4E ability (reworked mechanic, same name)
    "Incorporeal",      # M4E ability (reworked mechanic, same name)
    "Companion",        # M4E ability name (new mechanic)
    "Accomplice",       # M4E ability name (new mechanic)
    "Black Blood",      # M4E crew ability (Nephilim keyword)
    "cheating fate",    # Grammatically correct gerund of "cheat fate"
    "Stack the Deck",   # Card-game themed ability name
    "Search the Stacks",  # Library themed action
}

# ── Token timing validation ────────────────────────────────────────────
VALID_TIMINGS = {"end_phase", "end_activation", "on_use", "permanent", "never", "when_triggered"}

# ── Tables and their text columns to scan ──────────────────────────────
SCAN_TABLES = {
    "models": ["name", "title"],
    "abilities": ["name", "text"],
    "actions": ["name", "effects", "costs_and_restrictions"],
    "triggers": ["name", "text"],
    "tokens": ["name", "rules_text"],
    "crew_tokens": ["name", "text"],
    "crew_keyword_abilities": ["name", "text"],
    "crew_keyword_actions": ["name", "effects", "costs_and_restrictions"],
    "crew_keyword_action_triggers": ["name", "text"],
    "upgrade_abilities": ["name", "text"],
    "upgrade_actions": ["name", "effects", "costs_and_restrictions"],
    "upgrade_universal_triggers": ["name", "text"],
    "rules_sections": ["title", "content"],
    "faq_entries": ["question", "answer"],
    "markers": ["name", "rules_text"],
}


def get_model_context(conn: sqlite3.Connection, table: str, row: dict) -> str:
    """Get human-readable context for a row (model name, etc.)."""
    c = conn.cursor()

    if table == "models":
        return f"{row.get('name', '?')} (id={row.get('id', '?')})"

    if table in ("abilities", "actions"):
        mid = row.get("model_id")
        if mid:
            m = c.execute("SELECT name FROM models WHERE id=?", (mid,)).fetchone()
            return f"{m['name'] if m else '?'} → {row.get('name', '?')}"

    if table == "triggers":
        aid = row.get("action_id")
        if aid:
            a = c.execute(
                "SELECT a.name, m.name as model_name FROM actions a JOIN models m ON a.model_id=m.id WHERE a.id=?",
                (aid,),
            ).fetchone()
            if a:
                return f"{a['model_name']} → {a['name']} → {row.get('name', '?')}"

    if table == "tokens":
        return f"token: {row.get('name', '?')}"

    if table == "crew_tokens":
        ccid = row.get("crew_card_id")
        if ccid:
            cc = c.execute("SELECT name FROM crew_cards WHERE id=?", (ccid,)).fetchone()
            return f"{cc['name'] if cc else '?'} → {row.get('name', '?')}"

    if table.startswith("crew_keyword"):
        ccid = row.get("crew_card_id")
        if ccid:
            cc = c.execute("SELECT name FROM crew_cards WHERE id=?", (ccid,)).fetchone()
            return f"{cc['name'] if cc else '?'} → {row.get('name', '?')}"

    if table.startswith("upgrade"):
        uid = row.get("upgrade_id")
        if uid:
            u = c.execute("SELECT name FROM upgrades WHERE id=?", (uid,)).fetchone()
            return f"{u['name'] if u else '?'} → {row.get('name', '?')}"

    if table == "rules_sections":
        return f"rules: {row.get('title', '?')}"

    if table == "faq_entries":
        q = row.get("question", "?")
        return f"FAQ: {q[:60]}..."

    if table == "markers":
        return f"marker: {row.get('name', '?')}"

    return str(row.get("id", "?"))


def is_false_positive(match_text: str, field_text: str) -> bool:
    """Check if a match is a known false positive."""
    for fp in FALSE_POSITIVES:
        if fp.lower() in field_text.lower():
            # Check if the match is part of the false positive
            if match_text.strip().lower() in fp.lower() or fp.lower() in match_text.strip().lower():
                return True
    return False


def scan_database(conn: sqlite3.Connection, verbose: bool = False) -> list[dict]:
    """Scan all text fields in all tables for M3E terminology."""
    findings = []
    c = conn.cursor()

    for table, columns in SCAN_TABLES.items():
        # Check if table exists
        exists = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            continue

        # Get actual columns
        actual_cols = {ci["name"] for ci in c.execute(f"PRAGMA table_info({table})").fetchall()}
        valid_cols = [col for col in columns if col in actual_cols]
        if not valid_cols:
            continue

        rows = c.execute(f"SELECT * FROM {table}").fetchall()

        for row in rows:
            row_dict = dict(row)
            for col in valid_cols:
                text = row_dict.get(col)
                if not text or not isinstance(text, str):
                    continue

                # Check hard terms
                for pattern, desc, severity, note in M3E_HARD_TERMS:
                    matches = list(re.finditer(pattern, text, re.IGNORECASE))
                    for m in matches:
                        match_text = m.group()
                        if is_false_positive(match_text, text):
                            continue

                        context = get_model_context(conn, table, row_dict)
                        finding = {
                            "severity": severity,
                            "term": desc,
                            "table": table,
                            "column": col,
                            "context": context,
                            "match": match_text,
                            "snippet": text[max(0, m.start() - 30):m.end() + 30],
                        }
                        if note:
                            finding["note"] = note
                        findings.append(finding)

                # Check soft terms (only in verbose mode)
                if verbose:
                    for pattern, desc, severity, note in M3E_SOFT_TERMS:
                        matches = list(re.finditer(pattern, text, re.IGNORECASE))
                        for m in matches:
                            match_text = m.group()
                            if is_false_positive(match_text, text):
                                continue

                            context = get_model_context(conn, table, row_dict)
                            finding = {
                                "severity": severity,
                                "term": desc,
                                "table": table,
                                "column": col,
                                "context": context,
                                "match": match_text,
                                "snippet": text[max(0, m.start() - 30):m.end() + 30],
                            }
                            if note:
                                finding["note"] = note
                            findings.append(finding)

    return findings


def check_token_integrity(conn: sqlite3.Connection) -> list[dict]:
    """Check tokens for timing/rules_text consistency and M3E contamination."""
    findings = []
    c = conn.cursor()
    rows = c.execute("SELECT * FROM tokens ORDER BY name").fetchall()

    for row in rows:
        name = row["name"]
        timing = row["timing"]
        rules = row["rules_text"] or ""

        # Check for invalid timing values
        if timing and timing not in VALID_TIMINGS:
            findings.append({
                "severity": "error",
                "term": "Invalid token timing",
                "table": "tokens",
                "column": "timing",
                "context": f"token: {name}",
                "match": timing,
                "snippet": f"timing='{timing}' not in {VALID_TIMINGS}",
            })

        # Check for M3E stacking language
        if re.search(r"equal to\s+(?:its\s+)?value", rules, re.IGNORECASE):
            findings.append({
                "severity": "error",
                "term": "M3E token stacking (value-based damage)",
                "table": "tokens",
                "column": "rules_text",
                "context": f"token: {name}",
                "match": rules[:80],
                "snippet": rules,
            })

        # Check for AI-summary markers
        if re.search(r"Keyword:\s", rules):
            findings.append({
                "severity": "warning",
                "term": "AI-generated summary (not actual rules text)",
                "table": "tokens",
                "column": "rules_text",
                "context": f"token: {name}",
                "match": rules[:80],
                "snippet": rules,
            })

        # Check timing vs rules_text consistency
        if timing != "end_phase" and re.search(
            r"[Dd]uring the end phase.*remove this token", rules
        ):
            findings.append({
                "severity": "warning",
                "term": "Timing/rules_text mismatch (text says end_phase removal)",
                "table": "tokens",
                "column": "timing",
                "context": f"token: {name}",
                "match": f"timing={timing}",
                "snippet": f"Text says end phase removal but timing={timing}",
            })

        if timing != "end_activation" and re.search(
            r"ends its activation.*remove this token", rules
        ):
            # Suppress false positive: Reload's "ends its activation" refers to
            # another model's activation triggering voluntary removal (on_use)
            if timing == "on_use" and "may remove this token" in rules:
                pass  # Voluntary removal triggered by external event = on_use
            else:
                findings.append({
                    "severity": "warning",
                    "term": "Timing/rules_text mismatch (text says end_activation removal)",
                    "table": "tokens",
                    "column": "timing",
                    "context": f"token: {name}",
                    "match": f"timing={timing}",
                    "snippet": f"Text says end_activation removal but timing={timing}",
                })

        # Check for NULL timing
        if timing is None:
            findings.append({
                "severity": "warning",
                "term": "Missing token timing",
                "table": "tokens",
                "column": "timing",
                "context": f"token: {name}",
                "match": "NULL",
                "snippet": f"Token '{name}' has no timing set",
            })

    return findings


def check_data_quality(conn: sqlite3.Connection) -> list[dict]:
    """Check for general data quality issues."""
    findings = []
    c = conn.cursor()

    # Check for unusual model name capitalization
    rows = c.execute("SELECT id, name FROM models").fetchall()
    for row in rows:
        name = row["name"]
        # Check for all-lowercase, weird mixed case, etc.
        if name and (name != name.strip() or name[0].islower()):
            findings.append({
                "severity": "warning",
                "term": "Unusual model name capitalization",
                "table": "models",
                "column": "name",
                "context": f"id={row['id']}",
                "match": name,
                "snippet": f"Model name '{name}' has unusual capitalization",
            })

    # Check for Versatile in keywords (should be characteristic)
    versatile_in_kw = c.execute(
        "SELECT mk.model_id, m.name FROM model_keywords mk JOIN models m ON mk.model_id=m.id WHERE mk.keyword='Versatile'"
    ).fetchall()
    for row in versatile_in_kw:
        findings.append({
            "severity": "error",
            "term": "Versatile in keywords (should be characteristic)",
            "table": "model_keywords",
            "column": "keyword",
            "context": f"{row['name']} (id={row['model_id']})",
            "match": "Versatile",
            "snippet": "Versatile is a characteristic in M4E, not a keyword",
        })

    # Check for Enforcer station in models
    enforcer = c.execute(
        "SELECT id, name, station FROM models WHERE station='Enforcer'"
    ).fetchall()
    for row in enforcer:
        findings.append({
            "severity": "error",
            "term": "Enforcer station (M3E only)",
            "table": "models",
            "column": "station",
            "context": f"{row['name']} (id={row['id']})",
            "match": "Enforcer",
            "snippet": "M4E has no Enforcer station",
        })

    # Check for duplicate models (same name, same faction, same title)
    # Note: Masters legitimately have multiple entries (one per title)
    dupes = c.execute("""
        SELECT name, title, faction, COUNT(*) as cnt
        FROM models
        GROUP BY name COLLATE NOCASE, title COLLATE NOCASE, faction COLLATE NOCASE
        HAVING cnt > 1
    """).fetchall()
    for row in dupes:
        findings.append({
            "severity": "warning",
            "term": "Possible duplicate model entries",
            "table": "models",
            "column": "name",
            "context": f"{row['name']} / {row['title']} / {row['faction']}",
            "match": f"{row['cnt']} entries",
            "snippet": f"Model '{row['name']}' ({row['title']}) appears {row['cnt']} times in {row['faction']}",
        })

    return findings


def scan_json_exports(verbose: bool = False) -> list[dict]:
    """Scan JSON export files for M3E contamination."""
    findings = []

    tokens_path = JSON_DIR / "m4e_tokens.json"
    if tokens_path.exists():
        with open(tokens_path, encoding="utf-8") as f:
            tokens = json.load(f)

        for tok in tokens:
            rules = tok.get("rules_text", "")
            timing = tok.get("timing")
            name = tok.get("name", "?")

            if re.search(r"equal to\s+(?:its\s+)?value", rules, re.IGNORECASE):
                findings.append({
                    "severity": "error",
                    "term": "M3E token stacking in JSON export",
                    "table": "m4e_tokens.json",
                    "column": "rules_text",
                    "context": f"token: {name}",
                    "match": rules[:80],
                    "snippet": rules,
                })

            if re.search(r"Keyword:\s", rules):
                findings.append({
                    "severity": "warning",
                    "term": "AI-generated summary in JSON export",
                    "table": "m4e_tokens.json",
                    "column": "rules_text",
                    "context": f"token: {name}",
                    "match": rules[:80],
                    "snippet": rules,
                })

    return findings


def main():
    parser = argparse.ArgumentParser(description="Detect M3E contamination in M4E data")
    parser.add_argument("--verbose", "-v", action="store_true", help="Include soft checks (info-level)")
    parser.add_argument("--export", type=str, help="Export findings to JSON file")
    args = parser.parse_args()

    print("=" * 70)
    print("M4E Data Integrity Check — M3E Contamination Detection")
    print("=" * 70)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Run all checks
    all_findings = []

    print("\n── Scanning database text fields ──")
    db_findings = scan_database(conn, verbose=args.verbose)
    all_findings.extend(db_findings)

    print("── Checking token integrity ──")
    token_findings = check_token_integrity(conn)
    all_findings.extend(token_findings)

    print("── Checking data quality ──")
    quality_findings = check_data_quality(conn)
    all_findings.extend(quality_findings)

    print("── Scanning JSON exports ──")
    json_findings = scan_json_exports(verbose=args.verbose)
    all_findings.extend(json_findings)

    conn.close()

    # Categorize findings
    errors = [f for f in all_findings if f["severity"] == "error"]
    warnings = [f for f in all_findings if f["severity"] == "warning"]
    info = [f for f in all_findings if f["severity"] == "info"]

    # Print results
    if errors:
        print(f"\n{'─' * 70}")
        print(f"  ERRORS ({len(errors)})")
        print(f"{'─' * 70}")
        for f in errors:
            print(f"  ✗ [{f['table']}.{f['column']}] {f['term']}")
            print(f"    {f['context']}: {f['match']}")
            if f.get("note"):
                print(f"    Note: {f['note']}")
            print()

    if warnings:
        print(f"\n{'─' * 70}")
        print(f"  WARNINGS ({len(warnings)})")
        print(f"{'─' * 70}")
        for f in warnings:
            print(f"  ⚠ [{f['table']}.{f['column']}] {f['term']}")
            print(f"    {f['context']}: {f['match']}")
            if f.get("note"):
                print(f"    Note: {f['note']}")
            print()

    if info and args.verbose:
        print(f"\n{'─' * 70}")
        print(f"  INFO ({len(info)})")
        print(f"{'─' * 70}")
        for f in info:
            print(f"  ℹ [{f['table']}.{f['column']}] {f['term']}")
            print(f"    {f['context']}: {f['match']}")
            if f.get("note"):
                print(f"    Note: {f['note']}")
            print()

    # Summary
    print(f"\n{'=' * 70}")
    if not errors and not warnings:
        print("  CLEAN: No M3E contamination detected")
    print(f"  Errors: {len(errors)}  |  Warnings: {len(warnings)}  |  Info: {len(info)}")
    print(f"{'=' * 70}")

    # Export
    if args.export:
        export_path = Path(args.export)
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(all_findings, f, indent=2, ensure_ascii=False)
        print(f"\nFindings exported to: {export_path}")

    return len(errors)


if __name__ == "__main__":
    exit(main())
