#!/usr/bin/env python3
"""Load strategy and scheme card data from PDFs into the M4E database.

Extracts structured game data directly from strategy/scheme card PDFs
using PyMuPDF font-based text parsing, then loads into SQLite.

Idempotent: deletes existing rows before inserting.

Usage:
    python scripts/load_rules_data.py [--db DB_PATH] [--source-dir DIR]
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    raise SystemExit("PyMuPDF required: pip install PyMuPDF")

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "m4e.db"
SOURCE_DIR = Path(__file__).resolve().parent.parent / "source_pdfs" / "Rules and Objectives"

# Strategy suit assignments (from Gaining Grounds rules)
STRATEGY_SUITS = {
    "Boundary Dispute": "(m)",
    "Informants": "(r)",
    "Plant Explosives": "(t)",
    "Recover Evidence": "(c)",
}


def _extract_card_from_pdf(pdf_path: Path) -> dict:
    """Extract structured card data from a strategy or scheme PDF.

    Parses font metadata to identify:
    - Title: Astoria-Bold at 16.5pt
    - VP count: Wingdings 'q' characters
    - Section headers: HarriText-ExtraBold at 9pt
    - Body text: HarriText-Regular at 7pt
    - Selection/preamble: HarriText-Italic at 7pt (schemes only)
    - Bold keywords: HarriText-Bold at 7pt (inline, merged with body)
    - Next available schemes: HarriText-Bold at 7.8pt
    """
    doc = fitz.open(str(pdf_path))
    page = doc[0]
    blocks = page.get_text("dict")["blocks"]

    title_parts = []
    max_vp = 0
    selection_lines = []
    sections = {}
    current_section = None
    current_lines = []
    next_schemes = []
    card_type = None  # "Strategy" or "Scheme"

    for block in blocks:
        if "lines" not in block:
            continue
        for line in block["lines"]:
            line_text_parts = []
            has_header = False
            header_text = ""

            for span in line["spans"]:
                font = span["font"]
                size = span["size"]
                text = span["text"]

                # Card type label
                if font == "Astoria-Bold" and size < 10:
                    card_type = text.strip()

                # Title spans (may wrap across lines)
                elif font == "Astoria-Bold" and size > 14:
                    title_parts.append(text.strip())

                # VP dots (Wingdings 'q' = one VP pip)
                elif font == "Wingdings-Regular":
                    max_vp = text.count("q")

                # Section headers
                elif font == "HarriText-ExtraBold" and size >= 9.0:
                    has_header = True
                    header_text = text.strip()

                # Selection/preamble text (italic, before first section)
                elif font == "HarriText-Italic" and size < 8:
                    t = text.strip()
                    if t:
                        selection_lines.append(t)

                # Next available scheme names
                elif font == "HarriText-Bold" and 7.5 < size < 8.5:
                    t = text.strip()
                    if t:
                        next_schemes.append(t)

                # Body text (regular + inline bold keywords)
                elif font in ("HarriText-Regular", "HarriText-Bold") and size < 8:
                    line_text_parts.append(text)

                # Bullet character (ArponaSans)
                elif font == "ArponaSans-Regular":
                    line_text_parts.append("\u2022")

            if has_header:
                # Save previous section
                if current_section and current_lines:
                    sections[current_section] = _join_lines(current_lines)
                current_section = header_text
                current_lines = []
            elif current_section and current_section != "NEXT AVAILABLE SCHEMES":
                combined = "".join(line_text_parts).strip()
                if combined and combined != "\t":
                    current_lines.append(combined)

    # Save last section
    if current_section and current_lines:
        sections[current_section] = _join_lines(current_lines)

    doc.close()

    # Build title from collected parts
    name = " ".join(title_parts)
    # Proper title case (keeps articles lowercase)
    name = _title_case(name)

    return {
        "card_type": card_type,
        "name": name,
        "max_vp": max_vp,
        "selection": _join_lines(selection_lines) if selection_lines else None,
        "sections": sections,
        "next_available_schemes": next_schemes,
    }


def _title_case(text: str) -> str:
    """Convert ALL-CAPS text to proper title case, keeping small words lowercase."""
    small_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
                   "for", "of", "with", "by", "from", "it", "is"}
    words = text.title().split()
    result = []
    for i, word in enumerate(words):
        if i > 0 and word.lower() in small_words:
            result.append(word.lower())
        else:
            result.append(word)
    return " ".join(result)


def _join_lines(lines: list[str]) -> str:
    """Join extracted text lines into a single paragraph, cleaning whitespace."""
    text = " ".join(lines)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)
    # Fix bullet formatting
    text = text.replace("\u2022 \t", "\u2022 ")
    return text.strip()


def _name_to_id(prefix: str, name: str) -> str:
    """Convert a card name to a snake_case ID."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"{prefix}_{slug}"


def extract_strategies(source_dir: Path) -> list[dict]:
    """Extract all strategy cards from PDFs."""
    strategy_dir = source_dir / "Strategy Cards"
    if not strategy_dir.exists():
        print(f"  WARNING: {strategy_dir} not found")
        return []

    strategies = []
    for pdf_path in sorted(strategy_dir.glob("M4E_Strategy_*.pdf")):
        card = _extract_card_from_pdf(pdf_path)
        name = card["name"]
        strategy = {
            "id": _name_to_id("strategy", name),
            "name": name,
            "suit": STRATEGY_SUITS.get(name),
            "max_vp": card["max_vp"],
            "setup": card["sections"].get("SETUP"),
            "rules": card["sections"].get("RULES"),
            "scoring": card["sections"].get("SCORING"),
            "additional_vp": card["sections"].get("ADDITIONAL VP"),
        }
        strategies.append(strategy)

    return strategies


def extract_schemes(source_dir: Path) -> list[dict]:
    """Extract all scheme cards from PDFs."""
    scheme_dir = source_dir / "Scheme Cards"
    if not scheme_dir.exists():
        print(f"  WARNING: {scheme_dir} not found")
        return []

    schemes = []
    for pdf_path in sorted(scheme_dir.glob("M4E_Scheme_*.pdf")):
        card = _extract_card_from_pdf(pdf_path)
        name = card["name"]
        scheme = {
            "id": _name_to_id("scheme", name),
            "name": name,
            "max_vp": card["max_vp"],
            "selection": card["selection"],
            "reveal": card["sections"].get("REVEAL"),
            "scoring": card["sections"].get("SCORING"),
            "additional_vp": card["sections"].get("ADDITIONAL VP"),
            "next_available_schemes": card["next_available_schemes"],
        }
        schemes.append(scheme)

    return schemes


def load_strategies(conn: sqlite3.Connection, strategies: list[dict]) -> int:
    """Load strategy data into the database."""
    conn.execute("DELETE FROM strategies")
    conn.executemany(
        "INSERT INTO strategies (id, name, suit, max_vp, setup, rules, scoring, additional_vp) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (s["id"], s["name"], s.get("suit"), s["max_vp"],
             s.get("setup"), s.get("rules"), s.get("scoring"), s.get("additional_vp"))
            for s in strategies
        ],
    )
    return len(strategies)


def load_schemes(conn: sqlite3.Connection, schemes: list[dict]) -> int:
    """Load scheme data into the database."""
    conn.execute("DELETE FROM schemes")
    conn.executemany(
        "INSERT INTO schemes (id, name, max_vp, selection, reveal, scoring, additional_vp, next_available_schemes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (s["id"], s["name"], s["max_vp"], s.get("selection"),
             s.get("reveal"), s.get("scoring"), s.get("additional_vp"),
             json.dumps(s.get("next_available_schemes", [])))
            for s in schemes
        ],
    )
    return len(schemes)


def main():
    parser = argparse.ArgumentParser(description="Load strategy/scheme card data into M4E database")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Path to SQLite database")
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR, help="Path to source PDF directory")
    parser.add_argument("--dry-run", action="store_true", help="Extract and print without loading to DB")
    args = parser.parse_args()

    print("Extracting strategy cards from PDFs...")
    strategies = extract_strategies(args.source_dir)
    for s in strategies:
        print(f"  {s['suit'] or '??'} {s['name']} (max VP: {s['max_vp']})")

    print(f"\nExtracting scheme cards from PDFs...")
    schemes = extract_schemes(args.source_dir)
    for s in schemes:
        next_str = ", ".join(s["next_available_schemes"]) if s["next_available_schemes"] else "none"
        print(f"  {s['name']} (max VP: {s['max_vp']}) -> [{next_str}]")

    if args.dry_run:
        print(f"\nDry run: {len(strategies)} strategies, {len(schemes)} schemes extracted.")
        print("\nStrategy details:")
        for s in strategies:
            print(f"\n  === {s['name']} ===")
            for k in ("setup", "rules", "scoring", "additional_vp"):
                if s.get(k):
                    print(f"  {k}: {s[k]}")
        print("\nScheme details:")
        for s in schemes:
            print(f"\n  === {s['name']} ===")
            for k in ("selection", "reveal", "scoring", "additional_vp"):
                if s.get(k):
                    print(f"  {k}: {s[k]}")
        return

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        strat_count = load_strategies(conn, strategies)
        print(f"\n  strategies: {strat_count} rows loaded")

        scheme_count = load_schemes(conn, schemes)
        print(f"  schemes:    {scheme_count} rows loaded")

        conn.commit()
        print("\nDone.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
