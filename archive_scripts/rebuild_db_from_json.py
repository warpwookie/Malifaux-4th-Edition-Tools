#!/usr/bin/env python3
"""
rebuild_db_from_json.py - Rebuild m4e.db from corrected JSON export files.

Usage:
    python scripts/rebuild_db_from_json.py
"""
import sqlite3
import json
import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DB_PATH = REPO_ROOT / "db" / "m4e.db"
SCHEMA_PATH = REPO_ROOT / "schema" / "schema.sql"
JSON_DIR = REPO_ROOT / "Model Data Json"

FACTION_FILES = {
    "Arcanists": "m4e_models_arcanists.json",
    "Bayou": "m4e_models_bayou.json",
    "Explorer's Society": "m4e_models_explorers_society.json",
    "Guild": "m4e_models_guild.json",
    "Neverborn": "m4e_models_neverborn.json",
    "Outcasts": "m4e_models_outcasts.json",
    "Resurrectionists": "m4e_models_resurrectionists.json",
    "Ten Thunders": "m4e_models_ten_thunders.json",
}


def main():
    # Delete and recreate the DB fresh
    if DB_PATH.exists():
        os.remove(DB_PATH)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys=ON")

    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())

    c = conn.cursor()

    # ── Load all faction model files ─────────────────────────────────────
    total_models = 0

    for faction, fname in FACTION_FILES.items():
        fpath = JSON_DIR / fname
        with open(fpath, "r", encoding="utf-8") as f:
            models = json.load(f)

        for m in models:
            name = m["name"]
            title = m.get("title")
            model_faction = m.get("faction", faction)

            # Insert model
            c.execute(
                """INSERT INTO models (name, title, faction, station, model_limit, cost,
                    df, wp, sz, sp, health, soulstone_cache, shields, base_size,
                    infuses_soulstone_on_death, crew_card_name, totem,
                    source_pdf, parse_date, parse_status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (name, title, model_faction, m.get("station"), m.get("model_limit", 1),
                 m.get("cost"), m["df"], m["wp"], m["sz"], m["sp"],
                 m["health"], m.get("soulstone_cache"), m.get("shields", 0),
                 m.get("base_size"), m.get("infuses_soulstone_on_death", True),
                 m.get("crew_card_name"), m.get("totem"),
                 m.get("source_pdf"), datetime.now().isoformat(), "auto"))
            model_id = c.lastrowid

            # Keywords (with totem filter)
            totem_name = m.get("totem")
            for kw in m.get("keywords", []):
                if totem_name and kw == totem_name:
                    continue
                c.execute("INSERT OR IGNORE INTO model_keywords VALUES (?,?)",
                          (model_id, kw))

            # Characteristics
            for ch in m.get("characteristics", []):
                c.execute("INSERT OR IGNORE INTO model_characteristics VALUES (?,?)",
                          (model_id, ch))

            # Factions junction table
            c.execute("INSERT OR IGNORE INTO model_factions VALUES (?,?)",
                      (model_id, model_faction))

            # Abilities
            for ab in m.get("abilities", []):
                c.execute(
                    "INSERT INTO abilities (model_id, name, defensive_type, text) VALUES (?,?,?,?)",
                    (model_id, ab["name"], ab.get("defensive_type"), ab["text"]))

            # Actions (attack + tactical combined)
            all_actions = []
            for act in m.get("attack_actions", []):
                act["category"] = "attack_actions"
                all_actions.append(act)
            for act in m.get("tactical_actions", []):
                act["category"] = "tactical_actions"
                all_actions.append(act)

            for act in all_actions:
                c.execute(
                    """INSERT INTO actions (model_id, name, category, action_type, range,
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
                    c.execute(
                        """INSERT INTO triggers (action_id, name, suit, timing, text,
                            is_mandatory, soulstone_cost) VALUES (?,?,?,?,?,?,?)""",
                        (action_id, trig["name"], trig.get("suit"), trig.get("timing"),
                         trig["text"], trig.get("is_mandatory", False),
                         trig.get("soulstone_cost", 0)))

            total_models += 1

        print(f"  {faction}: {len(models)} models loaded")

    conn.commit()

    # ── Load crew cards ──────────────────────────────────────────────────
    crew_path = JSON_DIR / "m4e_crew_cards.json"
    if crew_path.exists():
        with open(crew_path, "r", encoding="utf-8") as f:
            crew_cards = json.load(f)

        crew_count = 0
        for cc in crew_cards:
            name = cc["name"]
            c.execute(
                """INSERT INTO crew_cards (name, associated_master, associated_title, faction,
                    source_pdf, parse_date, parse_status) VALUES (?,?,?,?,?,?,?)""",
                (name, cc.get("associated_master"), cc.get("associated_title"),
                 cc.get("faction"), cc.get("source_pdf"),
                 datetime.now().isoformat(), "auto"))
            crew_id = c.lastrowid

            # Keyword abilities
            for ka in cc.get("keyword_abilities", []):
                for ab in ka.get("abilities", []):
                    c.execute(
                        """INSERT INTO crew_keyword_abilities
                            (crew_card_id, granted_to, name, defensive_type, text)
                            VALUES (?,?,?,?,?)""",
                        (crew_id, ka.get("granted_to"), ab["name"],
                         ab.get("defensive_type"), ab["text"]))

            # Keyword actions
            for ka in cc.get("keyword_actions", []):
                for act in ka.get("actions", []):
                    c.execute(
                        """INSERT INTO crew_keyword_actions
                            (crew_card_id, granted_to, name, category, action_type, range,
                             skill_value, skill_built_in_suit, resist, tn, damage,
                             is_signature, soulstone_cost, effects, costs_and_restrictions)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (crew_id, ka.get("granted_to"), act["name"], act.get("category"),
                         act.get("action_type"), act.get("range"), act.get("skill_value"),
                         act.get("skill_built_in_suit"), act.get("resist"), act.get("tn"),
                         act.get("damage"), act.get("is_signature", False),
                         act.get("soulstone_cost", 0), act.get("effects"),
                         act.get("costs_and_restrictions")))
                    action_id = c.lastrowid
                    for trig in act.get("triggers", []):
                        c.execute(
                            """INSERT INTO crew_keyword_action_triggers
                                (crew_action_id, name, suit, timing, text,
                                 is_mandatory, soulstone_cost)
                                VALUES (?,?,?,?,?,?,?)""",
                            (action_id, trig["name"], trig.get("suit"),
                             trig.get("timing"), trig["text"],
                             trig.get("is_mandatory", False),
                             trig.get("soulstone_cost", 0)))

            # Markers
            for marker in cc.get("markers", []):
                c.execute(
                    """INSERT INTO crew_markers (crew_card_id, name, size, height, text)
                        VALUES (?,?,?,?,?)""",
                    (crew_id, marker["name"], marker.get("size"),
                     marker.get("height"), marker.get("text")))
                marker_id = c.lastrowid
                for trait in marker.get("terrain_traits", []):
                    c.execute("INSERT INTO crew_marker_terrain_traits VALUES (?,?)",
                              (marker_id, trait))

            # Tokens
            for token in cc.get("tokens", []):
                c.execute(
                    "INSERT INTO crew_tokens (crew_card_id, name, text) VALUES (?,?,?)",
                    (crew_id, token["name"], token["text"]))

            crew_count += 1

        conn.commit()
        print(f"\n  Crew cards: {crew_count} loaded")

    # ── Load tokens ──────────────────────────────────────────────────────
    tokens_path = JSON_DIR / "m4e_tokens.json"
    if tokens_path.exists():
        with open(tokens_path, "r", encoding="utf-8") as f:
            tokens = json.load(f)

        for t in tokens:
            c.execute("INSERT OR IGNORE INTO tokens (name) VALUES (?)", (t["name"],))

        conn.commit()
        print(f"  Tokens: {len(tokens)} loaded")

    # ── Final summary ────────────────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"Database rebuilt: {DB_PATH}")
    c.execute("SELECT COUNT(*) FROM models")
    print(f"  Models: {c.fetchone()[0]}")
    c.execute("SELECT COUNT(*) FROM model_keywords")
    print(f"  Keyword entries: {c.fetchone()[0]}")
    c.execute("SELECT COUNT(*) FROM actions")
    print(f"  Actions: {c.fetchone()[0]}")
    c.execute("SELECT COUNT(*) FROM triggers")
    print(f"  Triggers: {c.fetchone()[0]}")
    c.execute("SELECT COUNT(*) FROM crew_cards")
    print(f"  Crew cards: {c.fetchone()[0]}")

    # Verify no totem-as-keyword remains
    c.execute("""
        SELECT m.name, m.title, mk.keyword
        FROM model_keywords mk
        JOIN models m ON mk.model_id = m.id
        WHERE mk.keyword IN (SELECT DISTINCT name FROM models WHERE station = 'Totem')
        AND mk.keyword = m.totem
    """)
    remaining_bugs = c.fetchall()
    print(f"\n  Totem-as-keyword bugs remaining: {len(remaining_bugs)}")
    if remaining_bugs:
        for r in remaining_bugs:
            print(f"    STILL BAD: {r}")
    else:
        print("  All clean!")

    conn.close()


if __name__ == "__main__":
    main()
