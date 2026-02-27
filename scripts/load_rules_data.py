#!/usr/bin/env python3
"""Load rules, FAQ, and Gaining Grounds JSON data into the M4E database.

Reads the pre-extracted JSON files from source_pdfs/Rules and Objectives/
and populates the rules_sections, faq_entries, strategies, and schemes tables.

Idempotent: deletes existing rows before inserting.

Usage:
    python scripts/load_rules_data.py [--db DB_PATH] [--source-dir DIR]
"""

import argparse
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "m4e.db"
SOURCE_DIR = Path(__file__).resolve().parent.parent / "source_pdfs" / "Rules and Objectives"


def load_rules(conn: sqlite3.Connection, source_dir: Path) -> int:
    """Load rules sections from m4e_rules.json."""
    path = source_dir / "m4e_rules.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    sections = data["sections"]

    conn.execute("DELETE FROM rules_sections")
    conn.executemany(
        "INSERT INTO rules_sections (id, title, pages, content) VALUES (?, ?, ?, ?)",
        [
            (s["id"], s["title"], json.dumps(s["pages"]), s["content"])
            for s in sections
        ],
    )
    return len(sections)


def load_faq(conn: sqlite3.Connection, source_dir: Path) -> int:
    """Load FAQ entries from m4e_faq.json."""
    path = source_dir / "m4e_faq.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data["entries"]

    conn.execute("DELETE FROM faq_entries")
    conn.executemany(
        "INSERT OR REPLACE INTO faq_entries (id, section, section_number, question, answer) VALUES (?, ?, ?, ?, ?)",
        [
            (e["id"], e["section"], e["section_number"], e["question"], e["answer"])
            for e in entries
        ],
    )
    return len(entries)


def load_gaining_grounds(conn: sqlite3.Connection, source_dir: Path) -> dict:
    """Load strategies and schemes from m4e_gaining_grounds.json."""
    path = source_dir / "m4e_gaining_grounds.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    strategies = data["strategies"]
    schemes = data["schemes"]

    conn.execute("DELETE FROM strategies")
    conn.executemany(
        "INSERT INTO strategies (id, name, suit, max_vp, setup, rules, scoring, additional_vp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (s["id"], s["name"], s.get("suit"), s["max_vp"],
             s.get("setup"), s.get("rules"), s.get("scoring"), s.get("additional_vp"))
            for s in strategies
        ],
    )

    conn.execute("DELETE FROM schemes")
    conn.executemany(
        "INSERT INTO schemes (id, name, max_vp, selection, reveal, scoring, additional_vp, next_available_schemes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (s["id"], s["name"], s["max_vp"], s.get("selection"),
             s.get("reveal"), s.get("scoring"), s.get("additional_vp"),
             json.dumps(s.get("next_available_schemes", [])))
            for s in schemes
        ],
    )

    return {"strategies": len(strategies), "schemes": len(schemes)}


def main():
    parser = argparse.ArgumentParser(description="Load rules/FAQ/GG data into M4E database")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Path to SQLite database")
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR, help="Path to JSON source files")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        rules_count = load_rules(conn, args.source_dir)
        print(f"  rules_sections: {rules_count} rows loaded")

        faq_count = load_faq(conn, args.source_dir)
        print(f"  faq_entries:     {faq_count} rows loaded")

        gg_counts = load_gaining_grounds(conn, args.source_dir)
        print(f"  strategies:      {gg_counts['strategies']} rows loaded")
        print(f"  schemes:         {gg_counts['schemes']} rows loaded")

        conn.commit()
        print("Done.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
