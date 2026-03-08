#!/usr/bin/env python3
"""
db_loader.py â€” Load validated card JSON into the M4E SQLite database.

Handles both stat cards and crew cards. Supports upsert (update existing entries).
Automatically updates the token registry and parse log.

Usage:
    python db_loader.py card.json --db m4e.db
    python db_loader.py cards/*.json --db m4e.db --batch
"""
import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent.parent
SCHEMA_PATH = SCRIPT_DIR / "schema" / "schema.sql"
REFERENCE_PATH = SCRIPT_DIR / "reference" / "reference_data.json"

# Load reference data for allowlist-based matching.
_KNOWN_TOKENS = set()
_KNOWN_MARKERS = set()
_TOKEN_METADATA = {}    # {name: {type, timing, cancels}}
_MARKER_CATEGORIES = {} # {name: category}
try:
    with open(REFERENCE_PATH, encoding="utf-8") as _f:
        _ref = json.load(_f)
    _tokens_ref = _ref.get("tokens", {})
    _KNOWN_TOKENS = set(_tokens_ref.get("basic", {}).keys())
    # Store metadata for basic tokens
    for name, meta in _tokens_ref.get("basic", {}).items():
        _TOKEN_METADATA[name] = {
            "type": meta.get("type"),
            "timing": meta.get("timing"),
            "cancels": meta.get("cancels"),
        }
    # Also include tokens from cancellation pairs (e.g., Hidden, Exposed)
    for pair in _tokens_ref.get("cancellation_pairs", []):
        _KNOWN_TOKENS.update(pair)
    # Load known marker names (universal + keyword_specific)
    _markers_ref = _ref.get("markers", {})
    for category in ("universal", "keyword_specific"):
        for name in _markers_ref.get(category, []):
            _KNOWN_MARKERS.add(name)
            _MARKER_CATEGORIES[name] = category
except (FileNotFoundError, json.JSONDecodeError):
    pass


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize database with schema if needed."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")

    # Apply schema
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())

    # Seed basic token metadata from reference data
    c = conn.cursor()
    for name, meta in _TOKEN_METADATA.items():
        c.execute("INSERT OR IGNORE INTO tokens (name) VALUES (?)", (name,))
        c.execute("""UPDATE tokens SET type=?, timing=?, cancels=?
                     WHERE name=? AND type IS NULL""",
                  (meta["type"], meta["timing"], meta["cancels"], name))

    # Seed marker categories from reference data
    for name, category in _MARKER_CATEGORIES.items():
        c.execute("INSERT OR IGNORE INTO markers (name) VALUES (?)", (name,))
        c.execute("""UPDATE markers SET category=? WHERE name=? AND category IS NULL""",
                  (category, name))

    conn.commit()
    return conn


def load_stat_card(conn: sqlite3.Connection, card: dict, replace: bool = False) -> dict:
    """
    Insert or update a stat card in the database.
    Returns {"status": "inserted"|"updated"|"skipped", "model_id": int, ...}
    """
    c = conn.cursor()
    name = card["name"]
    title = card.get("title")
    faction = card["faction"]
    
    # Check if model already exists (case-insensitive name match)
    c.execute("SELECT id, name FROM models WHERE name=? COLLATE NOCASE AND title IS ? COLLATE NOCASE AND faction=?",
              (name, title, faction))
    existing = c.fetchone()
    
    if existing and not replace:
        return {"status": "skipped", "model_id": existing[0], 
                "reason": "Already exists (use --replace to update)"}
    
    if existing:
        model_id = existing[0]
        # Delete existing data for clean replace
        c.execute("DELETE FROM model_keywords WHERE model_id=?", (model_id,))
        c.execute("DELETE FROM model_characteristics WHERE model_id=?", (model_id,))
        c.execute("DELETE FROM model_factions WHERE model_id=?", (model_id,))
        # Cascading deletes handle abilities, actions, triggers
        c.execute("DELETE FROM abilities WHERE model_id=?", (model_id,))
        # Get action IDs for trigger cleanup
        c.execute("SELECT id FROM actions WHERE model_id=?", (model_id,))
        for (aid,) in c.fetchall():
            c.execute("DELETE FROM triggers WHERE action_id=?", (aid,))
        c.execute("DELETE FROM actions WHERE model_id=?", (model_id,))
        
        # Update model row
        c.execute("""UPDATE models SET faction=?, station=?, model_limit=?, cost=?,
            df=?, wp=?, sz=?, sp=?, health=?, base_size=?,
            infuses_soulstone_on_death=?, crew_card_name=?, totem=?,
            source_pdf=?, parse_date=?, parse_status=?
            WHERE id=?""",
            (faction, card.get("station"), card.get("model_limit", 1), card.get("cost"),
             card["df"], card["wp"], card["sz"], card["sp"], card["health"],
             card.get("base_size"),
             card.get("infuses_soulstone_on_death", True),
             card.get("crew_card_name"), card.get("totem"),
             card.get("source_pdf"), datetime.now().isoformat(), "auto",
             model_id))
        status = "updated"
    else:
        # Insert new model
        c.execute("""INSERT INTO models (name, title, faction, station, model_limit, cost,
            df, wp, sz, sp, health, base_size,
            infuses_soulstone_on_death, crew_card_name, totem,
            source_pdf, parse_date, parse_status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, title, faction, card.get("station"), card.get("model_limit", 1),
             card.get("cost"), card["df"], card["wp"], card["sz"], card["sp"],
             card["health"],
             card.get("base_size"), card.get("infuses_soulstone_on_death", True),
             card.get("crew_card_name"), card.get("totem"),
             card.get("source_pdf"), datetime.now().isoformat(), "auto"))
        model_id = c.lastrowid
        status = "inserted"
    
    # Keywords (filter out totem name — known ingestion error where vision AI
    # puts the totem name into the keywords array)
    totem_name = card.get("totem")
    for kw in card.get("keywords", []):
        if totem_name and kw == totem_name:
            continue
        c.execute("INSERT OR IGNORE INTO model_keywords VALUES (?,?)", (model_id, kw))
    
    # Characteristics
    for ch in card.get("characteristics", []):
        c.execute("INSERT OR IGNORE INTO model_characteristics VALUES (?,?)", (model_id, ch))
    
    # Factions (junction table for dual-faction models)
    factions = card.get("factions", [card.get("faction", "Unknown")])
    for fac in factions:
        c.execute("INSERT OR IGNORE INTO model_factions VALUES (?,?)", (model_id, fac))
    
    # Abilities
    for ab in card.get("abilities", []):
        c.execute("INSERT INTO abilities (model_id, name, defensive_type, text) VALUES (?,?,?,?)",
                  (model_id, ab["name"], ab.get("defensive_type"), ab["text"]))
    
    # Actions + triggers
    for act in card.get("actions", []):
        c.execute("""INSERT INTO actions (model_id, name, category, action_type, range,
            skill_value, skill_built_in_suit, skill_fate_modifier,
            resist, tn, damage, is_signature, soulstone_cost,
            effects, action_cost, restrictions, special_conditions)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (model_id, act["name"], act.get("category"), act.get("action_type"),
             act.get("range"), act.get("skill_value"), act.get("skill_built_in_suit"),
             act.get("skill_fate_modifier"), act.get("resist"), act.get("tn"),
             act.get("damage"),
             act.get("is_signature", False),
             act.get("soulstone_cost", 0), act.get("effects"),
             act.get("action_cost"), act.get("restrictions"),
             act.get("special_conditions")))
        action_id = c.lastrowid
        
        for trig in act.get("triggers", []):
            c.execute("""INSERT INTO triggers (action_id, name, suit, timing, text,
                is_mandatory, soulstone_cost) VALUES (?,?,?,?,?,?,?)""",
                (action_id, trig["name"], trig.get("suit"), trig.get("timing"),
                 trig["text"], trig.get("is_mandatory", False),
                 trig.get("soulstone_cost", 0)))
    
    # Auto-extract tokens mentioned in text
    _update_token_references(c, model_id, card)

    # Auto-extract marker references from text
    _update_marker_references(c, model_id, card)

    conn.commit()

    return {"status": status, "model_id": model_id, "name": name, "title": title}


def _update_token_references(c: sqlite3.Cursor, model_id: int, card: dict):
    """Scan card text for token references and update the token registry."""
    if not _KNOWN_TOKENS:
        return  # No reference data loaded, skip token extraction
    # Build regex from known token names only (prevents phantom tokens)
    names_alt = "|".join(re.escape(t) for t in sorted(_KNOWN_TOKENS, key=len, reverse=True))
    token_pattern = re.compile(r'\b(' + names_alt + r')\s+tokens?\b', re.IGNORECASE)
    # Also catch "X or Y token" pattern
    or_pattern = re.compile(
        r'\b(' + names_alt + r')\s+or\s+(?:a\s+|an\s+)?(' + names_alt + r')\s+tokens?\b',
        re.IGNORECASE
    )
    
    # Remove existing references for this model
    c.execute("""DELETE FROM token_model_sources WHERE model_id=?""", (model_id,))
    
    # Map lowercase -> canonical casing for consistent DB entries
    _canon = {t.lower(): t for t in _KNOWN_TOKENS}

    def register_token(token_name: str, source_type: str, source_name: str,
                       applies_or_references: str = "applies"):
        # Use canonical casing from reference data
        token_name = _canon.get(token_name.lower(), token_name)
        # Ensure token exists in registry
        c.execute("INSERT OR IGNORE INTO tokens (name) VALUES (?)", (token_name,))
        c.execute("SELECT id FROM tokens WHERE name=?", (token_name,))
        token_id = c.fetchone()[0]
        
        c.execute("""INSERT INTO token_model_sources 
                     (token_id, model_id, source_type, source_name, applies_or_references)
                     VALUES (?,?,?,?,?)""",
                  (token_id, model_id, source_type, source_name, applies_or_references))
    
    seen = set()  # (token_name, source_type, source_name, relationship) dedup

    def scan_text(text: str, source_type: str, source_name: str):
        if not text:
            return
        # Standard pattern
        for m in token_pattern.finditer(text):
            token_name = _canon.get(m.group(1).lower(), m.group(1))
            # Determine if applying or referencing
            context = text[max(0, m.start()-20):m.end()+10].lower()
            if any(w in context for w in ["gains", "gain", "receive", "apply"]):
                rel = "applies"
            elif any(w in context for w in ["remove", "removing", "lose"]):
                rel = "removes"
            else:
                rel = "references"
            key = (token_name, source_type, source_name, rel)
            if key not in seen:
                seen.add(key)
                register_token(token_name, source_type, source_name, rel)

        # "X or Y token" pattern
        for m in or_pattern.finditer(text):
            t1 = _canon.get(m.group(1).lower(), m.group(1))
            key = (t1, source_type, source_name, "applies")
            if key not in seen:
                seen.add(key)
                register_token(t1, source_type, source_name, "applies")

    # Scan abilities
    for ab in card.get("abilities", []):
        scan_text(ab.get("text", ""), "ability", ab.get("name", ""))
    
    # Scan actions
    for act in card.get("actions", []):
        scan_text(act.get("effects", ""), "action_effect", act.get("name", ""))
        for trig in act.get("triggers", []):
            scan_text(trig.get("text", ""), "trigger", 
                     f"{act.get('name', '')} > {trig.get('name', '')}")


def _update_marker_references(c: sqlite3.Cursor, model_id: int, card: dict):
    """Scan card text for marker references and update marker_model_sources.

    Uses _KNOWN_MARKERS allowlist (from reference_data.json) to prevent phantom
    markers, parallel to _update_token_references().
    """
    if not _KNOWN_MARKERS:
        return  # No reference data loaded, skip marker extraction

    # Build regex from known marker names (longest first for greedy matching)
    # Allow optional trailing "s" on name (e.g., "Pyrotechnics marker" → "Pyrotechnic")
    names_alt = "|".join(re.escape(m) for m in sorted(_KNOWN_MARKERS, key=len, reverse=True))
    marker_pattern = re.compile(r'\b(' + names_alt + r')s?\s+markers?\b', re.IGNORECASE)

    # Remove existing references for this model
    c.execute("DELETE FROM marker_model_sources WHERE model_id=?", (model_id,))

    # Map lowercase -> canonical casing for consistent DB entries
    _canon = {m.lower(): m for m in _KNOWN_MARKERS}

    create_words = {"make", "makes", "making", "made", "summon", "summons",
                    "place", "places", "placed", "create", "creates"}
    remove_words = {"remove", "removes", "removed", "removing", "discard", "discards",
                    "destroy", "destroys"}

    def register_marker(marker_name: str, source_type: str, source_name: str,
                        relationship: str = "references"):
        # Use canonical casing from reference data
        marker_name = _canon.get(marker_name.lower(), marker_name)
        # Ensure marker exists in registry
        c.execute("INSERT OR IGNORE INTO markers (name) VALUES (?)", (marker_name,))
        c.execute("SELECT id FROM markers WHERE name=?", (marker_name,))
        marker_id = c.fetchone()[0]
        c.execute("""INSERT INTO marker_model_sources
                     (marker_id, model_id, source_type, source_name, relationship)
                     VALUES (?,?,?,?,?)""",
                  (marker_id, model_id, source_type, source_name, relationship))

    seen = set()  # (marker_name, source_type, source_name, relationship) dedup

    def scan_text(text: str, source_type: str, source_name: str):
        if not text:
            return
        for m in marker_pattern.finditer(text):
            marker_name = _canon.get(m.group(1).lower(), m.group(1))
            start = max(0, m.start() - 30)
            context = text[start:m.end() + 10].lower()
            if any(w in context for w in create_words):
                rel = "creates"
            elif any(w in context for w in remove_words):
                rel = "removes"
            else:
                rel = "references"
            key = (marker_name, source_type, source_name, rel)
            if key not in seen:
                seen.add(key)
                register_marker(marker_name, source_type, source_name, rel)

    # Scan abilities
    for ab in card.get("abilities", []):
        scan_text(ab.get("text", ""), "ability", ab.get("name", ""))

    # Scan actions
    for act in card.get("actions", []):
        scan_text(act.get("effects", ""), "action_effect", act.get("name", ""))
        for trig in act.get("triggers", []):
            scan_text(trig.get("text", ""), "trigger",
                     f"{act.get('name', '')} > {trig.get('name', '')}")


def load_crew_card(conn: sqlite3.Connection, card: dict, replace: bool = False) -> dict:
    """Insert or update a crew card."""
    c = conn.cursor()
    name = card["name"]
    
    c.execute("SELECT id FROM crew_cards WHERE name=?", (name,))
    existing = c.fetchone()
    
    if existing and not replace:
        return {"status": "skipped", "reason": "Already exists"}
    
    if existing:
        crew_id = existing[0]
        c.execute("DELETE FROM crew_keyword_abilities WHERE crew_card_id=?", (crew_id,))
        c.execute("SELECT id FROM crew_keyword_actions WHERE crew_card_id=?", (crew_id,))
        for (aid,) in c.fetchall():
            c.execute("DELETE FROM crew_keyword_action_triggers WHERE crew_action_id=?", (aid,))
        c.execute("DELETE FROM crew_keyword_actions WHERE crew_card_id=?", (crew_id,))
        c.execute("DELETE FROM crew_markers WHERE crew_card_id=?", (crew_id,))
        c.execute("DELETE FROM crew_tokens WHERE crew_card_id=?", (crew_id,))
        
        c.execute("""UPDATE crew_cards SET associated_master=?, associated_title=?, faction=?,
            crew_tracker=?, source_pdf=?, parse_date=?, parse_status=? WHERE id=?""",
            (card["associated_master"], card["associated_title"], card["faction"],
             card.get("crew_tracker"), card.get("source_pdf"),
             datetime.now().isoformat(), "auto", crew_id))
        status = "updated"
    else:
        c.execute("""INSERT INTO crew_cards (name, associated_master, associated_title, faction,
            crew_tracker, source_pdf, parse_date, parse_status) VALUES (?,?,?,?,?,?,?,?)""",
            (name, card["associated_master"], card["associated_title"], card["faction"],
             card.get("crew_tracker"), card.get("source_pdf"),
             datetime.now().isoformat(), "auto"))
        crew_id = c.lastrowid
        status = "inserted"
    
    # Keyword abilities
    for ka in card.get("keyword_abilities", []):
        for ab in ka.get("abilities", []):
            c.execute("""INSERT INTO crew_keyword_abilities 
                (crew_card_id, granted_to, name, defensive_type, text) VALUES (?,?,?,?,?)""",
                (crew_id, ka["granted_to"], ab["name"], ab.get("defensive_type"), ab["text"]))
    
    # Keyword actions
    for ka in card.get("keyword_actions", []):
        for act in ka.get("actions", []):
            c.execute("""INSERT INTO crew_keyword_actions
                (crew_card_id, granted_to, name, category, action_type, range,
                 skill_value, skill_built_in_suit, resist, tn, damage,
                 is_signature, soulstone_cost, effects, action_cost,
                 restrictions, special_conditions)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (crew_id, ka["granted_to"], act["name"], act.get("category"),
                 act.get("action_type"), act.get("range"), act.get("skill_value"),
                 act.get("skill_built_in_suit"), act.get("resist"), act.get("tn"),
                 act.get("damage"), act.get("is_signature", False),
                 act.get("soulstone_cost", 0), act.get("effects"),
                 act.get("action_cost"), act.get("restrictions"),
                 act.get("special_conditions")))
            action_id = c.lastrowid
            for trig in act.get("triggers", []):
                c.execute("""INSERT INTO crew_keyword_action_triggers
                    (crew_action_id, name, suit, timing, text, is_mandatory, soulstone_cost)
                    VALUES (?,?,?,?,?,?,?)""",
                    (action_id, trig["name"], trig.get("suit"), trig.get("timing"),
                     trig["text"], trig.get("is_mandatory", False), trig.get("soulstone_cost", 0)))
    
    # Markers (per-card storage)
    for marker in card.get("markers", []):
        c.execute("""INSERT INTO crew_markers (crew_card_id, name, size, height, text)
            VALUES (?,?,?,?,?)""",
            (crew_id, marker["name"], marker.get("size"), marker.get("height"), marker.get("text")))
        cm_id = c.lastrowid
        traits = marker.get("terrain_traits", [])
        for trait in traits:
            c.execute("INSERT INTO crew_marker_terrain_traits VALUES (?,?)", (cm_id, trait))

        # Also upsert into global markers registry
        traits_csv = ", ".join(sorted(traits)) if traits else None
        rules_text = marker.get("rules_text") or marker.get("text")
        c.execute("INSERT OR IGNORE INTO markers (name) VALUES (?)", (marker["name"],))
        c.execute("""UPDATE markers SET category=?, default_size=?, default_height=?,
                     terrain_traits_csv=?, rules_text=? WHERE name=?""",
                  ("keyword_specific", marker.get("size"), marker.get("height"),
                   traits_csv, rules_text, marker["name"]))
        c.execute("SELECT id FROM markers WHERE name=?", (marker["name"],))
        global_marker_id = c.fetchone()[0]
        for trait in traits:
            c.execute("INSERT OR IGNORE INTO marker_terrain_traits (marker_id, trait) VALUES (?,?)",
                      (global_marker_id, trait))
        c.execute("INSERT OR IGNORE INTO marker_crew_sources (marker_id, crew_card_id) VALUES (?,?)",
                  (global_marker_id, crew_id))

    # Tokens (per-card storage + upsert into global tokens registry)
    for token in card.get("tokens", []):
        c.execute("INSERT INTO crew_tokens (crew_card_id, name, text) VALUES (?,?,?)",
                  (crew_id, token["name"], token["text"]))

        # Upsert into global tokens registry
        c.execute("INSERT OR IGNORE INTO tokens (name) VALUES (?)", (token["name"],))
        # Update rules_text if not already set (basic tokens keep reference_data values)
        c.execute("""UPDATE tokens SET rules_text=? WHERE name=? AND rules_text IS NULL""",
                  (token["text"], token["name"]))
        c.execute("SELECT id FROM tokens WHERE name=?", (token["name"],))
        global_token_id = c.fetchone()[0]
        c.execute("INSERT OR IGNORE INTO token_crew_sources (token_id, crew_card_id) VALUES (?,?)",
                  (global_token_id, crew_id))

    conn.commit()
    return {"status": status, "crew_card_id": crew_id, "name": name}


def log_parse(conn: sqlite3.Connection, source_pdf: str, model_name: str,
              status: str, validation_result: dict = None, notes: str = None):
    """Write an entry to the parse audit log."""
    c = conn.cursor()
    c.execute("""INSERT INTO parse_log (source_pdf, model_name, timestamp, status,
        hard_rule_violations, soft_rule_flags, hallucination_flags, notes)
        VALUES (?,?,?,?,?,?,?,?)""",
        (source_pdf, model_name, datetime.now().isoformat(), status,
         json.dumps(validation_result.get("hard_violations", [])) if validation_result else None,
         json.dumps(validation_result.get("soft_flags", [])) if validation_result else None,
         json.dumps(validation_result.get("hallucination_flags", [])) if validation_result else None,
         notes))
    conn.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load M4E card data into SQLite")
    parser.add_argument("input", nargs="+", help="Card JSON file(s)")
    parser.add_argument("--db", required=True, help="Database path")
    parser.add_argument("--replace", action="store_true", help="Replace existing entries")
    args = parser.parse_args()
    
    conn = init_db(args.db)
    
    for input_file in args.input:
        with open(input_file, encoding="utf-8") as f:
            card = json.load(f)
        
        card_type = card.get("card_type", "stat_card")
        
        if card_type == "crew_card":
            result = load_crew_card(conn, card, args.replace)
        elif card_type == "upgrade":
            result = load_upgrade_card(conn, card, args.replace)
        else:
            result = load_stat_card(conn, card, args.replace)
        
        label = result.get("name", "?") + (f" ({result.get('title')})" if result.get("title") else "")
        print(f"  {result['status'].upper():8s} {label}")
    
    # Summary
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM models")
    print(f"\nDatabase: {c.fetchone()[0]} models total")
    c.execute("SELECT COUNT(*) FROM crew_cards")
    print(f"          {c.fetchone()[0]} crew cards total")
    
    conn.close()


def load_upgrade_card(conn: sqlite3.Connection, card: dict, replace: bool = False) -> dict:
    """Insert or update an upgrade card."""
    c = conn.cursor()
    name = card["name"]
    
    c.execute("SELECT id FROM upgrades WHERE name=?", (name,))
    existing = c.fetchone()
    
    if existing and not replace:
        return {"status": "skipped", "reason": "Already exists", "name": name}
    
    if existing:
        upgrade_id = existing[0]
        c.execute("DELETE FROM upgrade_abilities WHERE upgrade_id=?", (upgrade_id,))
        c.execute("SELECT id FROM upgrade_actions WHERE upgrade_id=?", (upgrade_id,))
        for (aid,) in c.fetchall():
            c.execute("DELETE FROM upgrade_action_triggers WHERE action_id=?", (aid,))
        c.execute("DELETE FROM upgrade_actions WHERE upgrade_id=?", (upgrade_id,))
        c.execute("DELETE FROM upgrade_universal_triggers WHERE upgrade_id=?", (upgrade_id,))
        
        c.execute("""UPDATE upgrades SET upgrade_type=?, keyword=?, faction=?, limitations=?,
            description=?, source_pdf=?, parse_date=?, parse_status=? WHERE id=?""",
            (card.get("upgrade_type"), card.get("keyword"), card.get("faction"),
             card.get("limitations"), card.get("description"),
             card.get("source_pdf"), datetime.now().isoformat(), "auto", upgrade_id))
        status = "updated"
    else:
        c.execute("""INSERT INTO upgrades (name, upgrade_type, keyword, faction, limitations,
            description, source_pdf, parse_date, parse_status)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (name, card.get("upgrade_type"), card.get("keyword"), card.get("faction"),
             card.get("limitations"), card.get("description"),
             card.get("source_pdf"), datetime.now().isoformat(), "auto"))
        upgrade_id = c.lastrowid
        status = "inserted"
    
    for ab in card.get("granted_abilities", []):
        c.execute("""INSERT INTO upgrade_abilities (upgrade_id, name, defensive_type, text)
            VALUES (?,?,?,?)""",
            (upgrade_id, ab["name"], ab.get("defensive_type"), ab["text"]))
    
    for act in card.get("granted_actions", []):
        c.execute("""INSERT INTO upgrade_actions
            (upgrade_id, name, category, action_type, range, skill_value,
             skill_built_in_suit, skill_fate_modifier, resist, tn, damage,
             is_signature, soulstone_cost, effects, action_cost,
             restrictions, special_conditions)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (upgrade_id, act["name"], act.get("category", "tactical_actions"),
             act.get("action_type"), act.get("range"), act.get("skill_value"),
             act.get("skill_built_in_suit"), act.get("skill_fate_modifier"),
             act.get("resist"), act.get("tn"), act.get("damage"),
             act.get("is_signature", False), act.get("soulstone_cost", 0),
             act.get("effects"), act.get("action_cost"),
             act.get("restrictions"), act.get("special_conditions")))
        action_id = c.lastrowid
        for trig in act.get("triggers", []):
            c.execute("""INSERT INTO upgrade_action_triggers
                (action_id, name, suit, timing, text, is_mandatory, soulstone_cost)
                VALUES (?,?,?,?,?,?,?)""",
                (action_id, trig["name"], trig.get("suit"), trig.get("timing"),
                 trig["text"], trig.get("is_mandatory", False), trig.get("soulstone_cost", 0)))
    
    # Universal triggers (apply to all attack actions, e.g., Bestial Form)
    for trig in card.get("universal_triggers", []):
        c.execute("""INSERT INTO upgrade_universal_triggers
            (upgrade_id, name, suit, timing, text, is_mandatory, soulstone_cost)
            VALUES (?,?,?,?,?,?,?)""",
            (upgrade_id, trig["name"], trig.get("suit"), trig.get("timing"),
             trig["text"], trig.get("is_mandatory", False), trig.get("soulstone_cost", 0)))

    conn.commit()
    return {"status": status, "upgrade_id": upgrade_id, "name": name}

