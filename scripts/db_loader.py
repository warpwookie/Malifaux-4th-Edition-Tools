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
SCHEMA_PATH = SCRIPT_DIR / "db" / "schema.sql"


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize database with schema if needed."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    
    # Apply schema
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    
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
    
    # Check if model already exists
    c.execute("SELECT id FROM models WHERE name=? AND title IS ? AND faction=?",
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
        # Cascading deletes handle abilities, actions, triggers
        c.execute("DELETE FROM abilities WHERE model_id=?", (model_id,))
        # Get action IDs for trigger cleanup
        c.execute("SELECT id FROM actions WHERE model_id=?", (model_id,))
        for (aid,) in c.fetchall():
            c.execute("DELETE FROM triggers WHERE action_id=?", (aid,))
        c.execute("DELETE FROM actions WHERE model_id=?", (model_id,))
        
        # Update model row
        c.execute("""UPDATE models SET faction=?, station=?, model_limit=?, cost=?,
            df=?, wp=?, sz=?, sp=?, health=?, soulstone_cache=?, shields=?, base_size=?,
            infuses_soulstone_on_death=?, crew_card_name=?, totem=?,
            source_pdf=?, parse_date=?, parse_status=?
            WHERE id=?""",
            (faction, card.get("station"), card.get("model_limit", 1), card.get("cost"),
             card["df"], card["wp"], card["sz"], card["sp"], card["health"],
             card.get("soulstone_cache"), card.get("shields", 0), card.get("base_size"),
             card.get("infuses_soulstone_on_death", True),
             card.get("crew_card_name"), card.get("totem"),
             card.get("source_pdf"), datetime.now().isoformat(), "auto",
             model_id))
        status = "updated"
    else:
        # Insert new model
        c.execute("""INSERT INTO models (name, title, faction, station, model_limit, cost,
            df, wp, sz, sp, health, soulstone_cache, shields, base_size,
            infuses_soulstone_on_death, crew_card_name, totem,
            source_pdf, parse_date, parse_status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, title, faction, card.get("station"), card.get("model_limit", 1),
             card.get("cost"), card["df"], card["wp"], card["sz"], card["sp"],
             card["health"], card.get("soulstone_cache"), card.get("shields", 0),
             card.get("base_size"), card.get("infuses_soulstone_on_death", True),
             card.get("crew_card_name"), card.get("totem"),
             card.get("source_pdf"), datetime.now().isoformat(), "auto"))
        model_id = c.lastrowid
        status = "inserted"
    
    # Keywords
    for kw in card.get("keywords", []):
        c.execute("INSERT OR IGNORE INTO model_keywords VALUES (?,?)", (model_id, kw))
    
    # Characteristics
    for ch in card.get("characteristics", []):
        c.execute("INSERT OR IGNORE INTO model_characteristics VALUES (?,?)", (model_id, ch))
    
    # Abilities
    for ab in card.get("abilities", []):
        c.execute("INSERT INTO abilities (model_id, name, defensive_type, text) VALUES (?,?,?,?)",
                  (model_id, ab["name"], ab.get("defensive_type"), ab["text"]))
    
    # Actions + triggers
    for act in card.get("actions", []):
        c.execute("""INSERT INTO actions (model_id, name, category, action_type, range,
            skill_value, skill_built_in_suit, skill_fate_modifier,
            resist, tn, damage, is_signature, soulstone_cost,
            effects, costs_and_restrictions)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (model_id, act["name"], act.get("category"), act.get("action_type"),
             act.get("range"), act.get("skill_value"), act.get("skill_built_in_suit"),
             act.get("skill_fate_modifier"), act.get("resist"), act.get("tn"),
             act.get("damage"), act.get("is_signature", False),
             act.get("soulstone_cost", 0), act.get("effects"),
             act.get("costs_and_restrictions")))
        action_id = c.lastrowid
        
        for trig in act.get("triggers", []):
            c.execute("""INSERT INTO triggers (action_id, name, suit, timing, text,
                is_mandatory, soulstone_cost) VALUES (?,?,?,?,?,?,?)""",
                (action_id, trig["name"], trig.get("suit"), trig.get("timing"),
                 trig["text"], trig.get("is_mandatory", False),
                 trig.get("soulstone_cost", 0)))
    
    # Auto-extract tokens mentioned in text
    _update_token_references(c, model_id, card)
    
    conn.commit()
    
    return {"status": status, "model_id": model_id, "name": name, "title": title}


def _update_token_references(c: sqlite3.Cursor, model_id: int, card: dict):
    """Scan card text for token references and update the token registry."""
    token_pattern = re.compile(r'\b([A-Z][a-z]+)\s+token')
    # Also catch "X or Y token" pattern
    or_pattern = re.compile(r'\b([A-Z][a-z]+)\s+or\s+(?:a\s+|an\s+)?([A-Z][a-z]+)\s+token')
    
    # Remove existing references for this model
    c.execute("""DELETE FROM token_model_sources WHERE model_id=?""", (model_id,))
    
    def register_token(token_name: str, source_type: str, source_name: str, 
                       applies_or_references: str = "applies"):
        # Ensure token exists in registry
        c.execute("INSERT OR IGNORE INTO tokens (name) VALUES (?)", (token_name,))
        c.execute("SELECT id FROM tokens WHERE name=?", (token_name,))
        token_id = c.fetchone()[0]
        
        c.execute("""INSERT INTO token_model_sources 
                     (token_id, model_id, source_type, source_name, applies_or_references)
                     VALUES (?,?,?,?,?)""",
                  (token_id, model_id, source_type, source_name, applies_or_references))
    
    def scan_text(text: str, source_type: str, source_name: str):
        if not text:
            return
        # Standard pattern
        for m in token_pattern.finditer(text):
            token_name = m.group(1)
            # Determine if applying or referencing
            context = text[max(0, m.start()-20):m.end()+10].lower()
            if any(w in context for w in ["gains", "gain", "receive", "apply"]):
                register_token(token_name, source_type, source_name, "applies")
            elif any(w in context for w in ["remove", "removing", "lose"]):
                register_token(token_name, source_type, source_name, "removes")
            else:
                register_token(token_name, source_type, source_name, "references")
        
        # "X or Y token" pattern
        for m in or_pattern.finditer(text):
            t1 = m.group(1)
            # t2 already caught by standard pattern
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
            source_pdf=?, parse_date=?, parse_status=? WHERE id=?""",
            (card["associated_master"], card["associated_title"], card["faction"],
             card.get("source_pdf"), datetime.now().isoformat(), "auto", crew_id))
        status = "updated"
    else:
        c.execute("""INSERT INTO crew_cards (name, associated_master, associated_title, faction,
            source_pdf, parse_date, parse_status) VALUES (?,?,?,?,?,?,?)""",
            (name, card["associated_master"], card["associated_title"], card["faction"],
             card.get("source_pdf"), datetime.now().isoformat(), "auto"))
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
                 is_signature, soulstone_cost, effects, costs_and_restrictions)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (crew_id, ka["granted_to"], act["name"], act.get("category"),
                 act.get("action_type"), act.get("range"), act.get("skill_value"),
                 act.get("skill_built_in_suit"), act.get("resist"), act.get("tn"),
                 act.get("damage"), act.get("is_signature", False),
                 act.get("soulstone_cost", 0), act.get("effects"),
                 act.get("costs_and_restrictions")))
            action_id = c.lastrowid
            for trig in act.get("triggers", []):
                c.execute("""INSERT INTO crew_keyword_action_triggers
                    (crew_action_id, name, suit, timing, text, is_mandatory, soulstone_cost)
                    VALUES (?,?,?,?,?,?,?)""",
                    (action_id, trig["name"], trig.get("suit"), trig.get("timing"),
                     trig["text"], trig.get("is_mandatory", False), trig.get("soulstone_cost", 0)))
    
    # Markers
    for marker in card.get("markers", []):
        c.execute("""INSERT INTO crew_markers (crew_card_id, name, size, height, text)
            VALUES (?,?,?,?,?)""",
            (crew_id, marker["name"], marker.get("size"), marker.get("height"), marker.get("text")))
        marker_id = c.lastrowid
        for trait in marker.get("terrain_traits", []):
            c.execute("INSERT INTO crew_marker_terrain_traits VALUES (?,?)", (marker_id, trait))
    
    # Tokens
    for token in card.get("tokens", []):
        c.execute("INSERT INTO crew_tokens (crew_card_id, name, text) VALUES (?,?,?)",
                  (crew_id, token["name"], token["text"]))
    
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
        with open(input_file) as f:
            card = json.load(f)
        
        card_type = card.get("card_type", "stat_card")
        
        if card_type == "crew_card":
            result = load_crew_card(conn, card, args.replace)
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
