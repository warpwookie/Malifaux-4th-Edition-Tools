#!/usr/bin/env python3
"""
denormalize.py — Export the M4E relational database into denormalized JSON
suitable for use as project knowledge / knowledge base.

Each model becomes a self-contained document with all stats, keywords,
characteristics, abilities, actions (with triggers) nested inline.
Crew cards are similarly denormalized and linked to their masters.

Output: One JSON file per faction + a combined all-factions file + crew cards file.
"""

import sqlite3
import json
from pathlib import Path
from collections import defaultdict

_SCRIPT_DIR = Path(__file__).parent
DB_PATH = _SCRIPT_DIR.parent / "db" / "m4e.db"
OUT_DIR = _SCRIPT_DIR.parent / "Model Data Json"

# Fields to strip from denormalized output (internal DB IDs, redundant fields)
STRIP_MODEL_FIELDS = {"id", "parse_date", "parse_status", "source_pdf"}
STRIP_ABILITY_FIELDS = {"id", "model_id"}
STRIP_ACTION_FIELDS = {"id", "model_id"}
STRIP_TRIGGER_FIELDS = {"id", "action_id"}


def dict_factory(cursor, row):
    """SQLite row factory that returns dicts."""
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def clean_dict(d: dict, strip_keys: set) -> dict:
    """Remove internal keys and None values for cleaner output."""
    return {k: v for k, v in d.items() if k not in strip_keys and v is not None}


def clean_bool_fields(d: dict) -> dict:
    """Convert SQLite 0/1 integers to proper booleans for known bool fields."""
    bool_fields = {"is_signature", "is_mandatory", "infuses_soulstone_on_death"}
    for f in bool_fields:
        if f in d:
            d[f] = bool(d[f])
    return d


def export_models(conn: sqlite3.Connection) -> list[dict]:
    """Export all models with fully denormalized nested data."""
    c = conn.cursor()
    
    c.execute("SELECT * FROM models ORDER BY faction, name, title")
    models = c.fetchall()
    
    result = []
    for model in models:
        mid = model["id"]
        
        # Keywords
        c.execute("SELECT keyword FROM model_keywords WHERE model_id=? ORDER BY keyword", (mid,))
        keywords = [r["keyword"] for r in c.fetchall()]
        
        # Characteristics
        c.execute("SELECT characteristic FROM model_characteristics WHERE model_id=? ORDER BY characteristic", (mid,))
        characteristics = [r["characteristic"] for r in c.fetchall()]
        
        # Abilities
        c.execute("SELECT * FROM abilities WHERE model_id=? ORDER BY id", (mid,))
        abilities = [clean_bool_fields(clean_dict(a, STRIP_ABILITY_FIELDS)) for a in c.fetchall()]
        
        # Actions + triggers
        c.execute("SELECT * FROM actions WHERE model_id=? ORDER BY id", (mid,))
        actions_raw = c.fetchall()
        actions = []
        for act in actions_raw:
            aid = act["id"]
            c.execute("SELECT * FROM triggers WHERE action_id=? ORDER BY id", (aid,))
            triggers = [clean_bool_fields(clean_dict(t, STRIP_TRIGGER_FIELDS)) for t in c.fetchall()]
            
            action_clean = clean_bool_fields(clean_dict(act, STRIP_ACTION_FIELDS))
            if triggers:
                action_clean["triggers"] = triggers
            actions.append(action_clean)
        
        # Build denormalized model
        m = clean_bool_fields(clean_dict(model, STRIP_MODEL_FIELDS))
        m["keywords"] = keywords
        m["characteristics"] = characteristics
        m["abilities"] = abilities
        
        # Split actions into attack and tactical for readability
        attack_actions = [a for a in actions if a.get("category") == "attack_actions"]
        tactical_actions = [a for a in actions if a.get("category") == "tactical_actions"]
        if attack_actions:
            m["attack_actions"] = attack_actions
        if tactical_actions:
            m["tactical_actions"] = tactical_actions
        
        result.append(m)
    
    return result


def export_crew_cards(conn: sqlite3.Connection) -> list[dict]:
    """Export all crew cards with fully denormalized nested data."""
    c = conn.cursor()
    
    c.execute("SELECT * FROM crew_cards ORDER BY faction, name")
    crew_cards = c.fetchall()
    
    result = []
    for cc in crew_cards:
        cid = cc["id"]
        
        # Keyword abilities
        c.execute("SELECT * FROM crew_keyword_abilities WHERE crew_card_id=? ORDER BY id", (cid,))
        kw_abilities_raw = c.fetchall()
        kw_abilities = []
        for ka in kw_abilities_raw:
            clean = {k: v for k, v in ka.items() if k not in {"id", "crew_card_id"} and v is not None}
            kw_abilities.append(clean)
        
        # Keyword actions + their triggers
        c.execute("SELECT * FROM crew_keyword_actions WHERE crew_card_id=? ORDER BY id", (cid,))
        kw_actions_raw = c.fetchall()
        kw_actions = []
        for ka in kw_actions_raw:
            ka_id = ka["id"]
            c.execute("SELECT * FROM crew_keyword_action_triggers WHERE crew_action_id=? ORDER BY id", (ka_id,))
            triggers = []
            for t in c.fetchall():
                clean_t = {k: v for k, v in t.items() if k not in {"id", "crew_action_id"} and v is not None}
                clean_t = clean_bool_fields(clean_t)
                triggers.append(clean_t)
            
            clean_ka = {k: v for k, v in ka.items() if k not in {"id", "crew_card_id"} and v is not None}
            clean_ka = clean_bool_fields(clean_ka)
            if triggers:
                clean_ka["triggers"] = triggers
            kw_actions.append(clean_ka)
        
        # Markers
        c.execute("SELECT * FROM crew_markers WHERE crew_card_id=? ORDER BY id", (cid,))
        markers = []
        for mk in c.fetchall():
            mk_id = mk["id"]
            c.execute("SELECT trait FROM crew_marker_terrain_traits WHERE marker_id=?", (mk_id,))
            traits = [r["trait"] for r in c.fetchall()]
            clean_mk = {k: v for k, v in mk.items() if k not in {"id", "crew_card_id"} and v is not None}
            if traits:
                clean_mk["terrain_traits"] = traits
            markers.append(clean_mk)
        
        # Tokens
        c.execute("SELECT * FROM crew_tokens WHERE crew_card_id=? ORDER BY id", (cid,))
        tokens = []
        for tk in c.fetchall():
            clean_tk = {k: v for k, v in tk.items() if k not in {"id", "crew_card_id"} and v is not None}
            tokens.append(clean_tk)
        
        # Build crew card document
        crew = {
            "name": cc["name"],
            "associated_master": cc["associated_master"],
            "associated_title": cc["associated_title"],
            "faction": cc["faction"],
        }
        if kw_abilities:
            crew["keyword_abilities"] = kw_abilities
        if kw_actions:
            crew["keyword_actions"] = kw_actions
        if markers:
            crew["markers"] = markers
        if tokens:
            crew["tokens"] = tokens
        
        result.append(crew)
    
    return result


STRIP_UPGRADE_FIELDS = {"id", "parse_date", "parse_status", "source_pdf"}
STRIP_UPGRADE_ABILITY_FIELDS = {"id", "upgrade_id"}
STRIP_UPGRADE_ACTION_FIELDS = {"id", "upgrade_id"}
STRIP_UPGRADE_TRIGGER_FIELDS = {"id", "action_id", "upgrade_id"}


def export_upgrades(conn: sqlite3.Connection) -> list[dict]:
    """Export all upgrade cards with fully denormalized nested data."""
    c = conn.cursor()

    c.execute("SELECT * FROM upgrades ORDER BY faction, name")
    upgrades = c.fetchall()

    result = []
    for upg in upgrades:
        uid = upg["id"]

        # Abilities
        c.execute("SELECT * FROM upgrade_abilities WHERE upgrade_id=? ORDER BY id", (uid,))
        abilities = [clean_bool_fields(clean_dict(a, STRIP_UPGRADE_ABILITY_FIELDS)) for a in c.fetchall()]

        # Actions + triggers
        c.execute("SELECT * FROM upgrade_actions WHERE upgrade_id=? ORDER BY id", (uid,))
        actions_raw = c.fetchall()
        actions = []
        for act in actions_raw:
            aid = act["id"]
            c.execute("SELECT * FROM upgrade_action_triggers WHERE action_id=? ORDER BY id", (aid,))
            triggers = [clean_bool_fields(clean_dict(t, STRIP_UPGRADE_TRIGGER_FIELDS)) for t in c.fetchall()]

            action_clean = clean_bool_fields(clean_dict(act, STRIP_UPGRADE_ACTION_FIELDS))
            if triggers:
                action_clean["triggers"] = triggers
            actions.append(action_clean)

        # Universal triggers
        c.execute("SELECT * FROM upgrade_universal_triggers WHERE upgrade_id=? ORDER BY id", (uid,))
        universal_triggers = [clean_bool_fields(clean_dict(t, STRIP_UPGRADE_TRIGGER_FIELDS)) for t in c.fetchall()]

        # Build upgrade document
        u = clean_bool_fields(clean_dict(upg, STRIP_UPGRADE_FIELDS))
        if abilities:
            u["granted_abilities"] = abilities
        if actions:
            u["granted_actions"] = actions
        if universal_triggers:
            u["universal_triggers"] = universal_triggers

        result.append(u)

    return result


def export_token_registry(conn: sqlite3.Connection) -> list[dict]:
    """Export the global token registry."""
    c = conn.cursor()
    c.execute("SELECT * FROM tokens ORDER BY name")
    tokens = []
    for t in c.fetchall():
        clean = {k: v for k, v in t.items() if k != "id" and v is not None}
        tokens.append(clean)
    return tokens


def build_faction_summary(models: list[dict]) -> dict:
    """Build a quick summary of what's in each faction."""
    summary = {}
    for m in models:
        fac = m["faction"]
        if fac not in summary:
            summary[fac] = {"total_models": 0, "masters": [], "henchmen": [], 
                           "minions": 0, "totems": [], "keywords": set()}
        summary[fac]["total_models"] += 1
        station = m.get("station")
        name_str = m["name"] + (f", {m['title']}" if m.get("title") else "")
        if station == "Master":
            summary[fac]["masters"].append(name_str)
        elif station == "Henchman":
            summary[fac]["henchmen"].append(name_str)
        elif station == "Totem":
            summary[fac]["totems"].append(name_str)
        elif station == "Minion":
            summary[fac]["minions"] += 1
        for kw in m.get("keywords", []):
            summary[fac]["keywords"].add(kw)
    
    # Convert sets to sorted lists for JSON
    for fac in summary:
        summary[fac]["keywords"] = sorted(summary[fac]["keywords"])
    
    return summary


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = dict_factory
    
    # === Export models ===
    print("Exporting models...")
    all_models = export_models(conn)
    print(f"  Total: {len(all_models)} models")
    
    # Group by faction
    by_faction = defaultdict(list)
    for m in all_models:
        by_faction[m["faction"]].append(m)
    
    # Write per-faction files
    for faction, models in sorted(by_faction.items()):
        safe_name = faction.lower().replace("'", "").replace(" ", "_")
        path = OUT_DIR / f"m4e_models_{safe_name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(models, f, indent=2)
        print(f"  {faction}: {len(models)} models -> {path.name}")
    
    # Write combined file
    combined_path = OUT_DIR / "m4e_models_all.json"
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(all_models, f, indent=2)
    print(f"  Combined: {len(all_models)} models -> {combined_path.name}")
    
    # === Export crew cards ===
    print("\nExporting crew cards...")
    all_crew = export_crew_cards(conn)
    crew_path = OUT_DIR / "m4e_crew_cards.json"
    with open(crew_path, "w", encoding="utf-8") as f:
        json.dump(all_crew, f, indent=2)
    print(f"  Total: {len(all_crew)} crew cards -> {crew_path.name}")
    
    # === Export upgrades ===
    print("\nExporting upgrades...")
    all_upgrades = export_upgrades(conn)
    upgrades_path = OUT_DIR / "m4e_upgrades.json"
    with open(upgrades_path, "w", encoding="utf-8") as f:
        json.dump(all_upgrades, f, indent=2)
    print(f"  Total: {len(all_upgrades)} upgrades -> {upgrades_path.name}")

    # === Export token registry ===
    print("\nExporting token registry...")
    tokens = export_token_registry(conn)
    tokens_path = OUT_DIR / "m4e_tokens.json"
    with open(tokens_path, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)
    print(f"  Total: {len(tokens)} tokens -> {tokens_path.name}")
    
    # === Build faction summary ===
    print("\nBuilding faction summary...")
    summary = build_faction_summary(all_models)
    summary_path = OUT_DIR / "m4e_faction_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"  Summary -> {summary_path.name}")
    
    # === Stats ===
    total_abilities = sum(len(m.get("abilities", [])) for m in all_models)
    total_attacks = sum(len(m.get("attack_actions", [])) for m in all_models)
    total_tacticals = sum(len(m.get("tactical_actions", [])) for m in all_models)
    total_triggers = sum(
        len(a.get("triggers", []))
        for m in all_models
        for a in m.get("attack_actions", []) + m.get("tactical_actions", [])
    )
    
    print(f"\n{'='*50}")
    print(f"DENORMALIZATION COMPLETE")
    print(f"{'='*50}")
    print(f"  Models:       {len(all_models)}")
    print(f"  Crew Cards:   {len(all_crew)}")
    print(f"  Upgrades:     {len(all_upgrades)}")
    print(f"  Abilities:    {total_abilities}")
    print(f"  Attacks:      {total_attacks}")
    print(f"  Tacticals:    {total_tacticals}")
    print(f"  Triggers:     {total_triggers}")
    print(f"  Tokens:       {len(tokens)}")
    print(f"  Factions:     {len(by_faction)}")
    
    conn.close()
    
    # File size report
    print(f"\nFile sizes:")
    for p in sorted(OUT_DIR.glob("*.json")):
        size_kb = p.stat().st_size / 1024
        if size_kb > 1024:
            print(f"  {p.name:45s} {size_kb/1024:.1f} MB")
        else:
            print(f"  {p.name:45s} {size_kb:.0f} KB")


if __name__ == "__main__":
    main()
