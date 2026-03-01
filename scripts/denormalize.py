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
    """Export the global token registry with model sources."""
    c = conn.cursor()
    c.execute("SELECT * FROM tokens ORDER BY name")
    tokens = []
    for t in c.fetchall():
        tid = t["id"]
        clean = {k: v for k, v in t.items() if k != "id" and v is not None}

        # Get model sources
        c.execute("""SELECT m.name AS model_name, tms.source_type, tms.source_name,
                            tms.applies_or_references
                     FROM token_model_sources tms
                     JOIN models m ON m.id = tms.model_id
                     WHERE tms.token_id=? ORDER BY m.name, tms.source_name""", (tid,))
        sources = []
        for s in c.fetchall():
            src = {k: v for k, v in dict(s).items() if v is not None}
            sources.append(src)
        if sources:
            clean["model_sources"] = sources

        tokens.append(clean)
    return tokens


def export_marker_registry(conn: sqlite3.Connection) -> list[dict]:
    """Export the global marker registry with terrain traits and crew card sources."""
    c = conn.cursor()
    c.execute("SELECT * FROM markers ORDER BY category, name")
    markers = []
    for m in c.fetchall():
        mid = m["id"]

        # Get normalized terrain traits
        c.execute("SELECT trait FROM marker_terrain_traits WHERE marker_id=? ORDER BY trait", (mid,))
        traits = [r["trait"] for r in c.fetchall()]

        # Get crew card sources
        c.execute("""SELECT cc.name, cc.faction FROM marker_crew_sources mcs
            JOIN crew_cards cc ON mcs.crew_card_id = cc.id
            WHERE mcs.marker_id=? ORDER BY cc.name""", (mid,))
        crew_sources = [{"name": r["name"], "faction": r["faction"]} for r in c.fetchall()]

        clean = {k: v for k, v in m.items() if k not in {"id"} and v is not None}
        if traits:
            clean["terrain_traits"] = traits
        if crew_sources:
            clean["defined_on_crew_cards"] = crew_sources
        markers.append(clean)
    return markers


def export_rules(conn: sqlite3.Connection) -> list[dict]:
    """Export all rules sections."""
    c = conn.cursor()
    c.execute("SELECT * FROM rules_sections ORDER BY rowid")
    result = []
    for r in c.fetchall():
        entry = dict(r)
        # Parse pages JSON back to list
        if entry.get("pages"):
            entry["pages"] = json.loads(entry["pages"])
        result.append(entry)
    return result


def export_faq(conn: sqlite3.Connection) -> list[dict]:
    """Export all FAQ entries."""
    c = conn.cursor()
    c.execute("SELECT * FROM faq_entries ORDER BY section_number, id")
    return [dict(r) for r in c.fetchall()]


def export_gaining_grounds(conn: sqlite3.Connection) -> dict:
    """Export strategies and schemes as a combined dict."""
    c = conn.cursor()

    c.execute("SELECT * FROM strategies ORDER BY name")
    strategies = [dict(r) for r in c.fetchall()]

    c.execute("SELECT * FROM schemes ORDER BY name")
    schemes = []
    for s in c.fetchall():
        entry = dict(s)
        if entry.get("next_available_schemes"):
            entry["next_available_schemes"] = json.loads(entry["next_available_schemes"])
        schemes.append(entry)

    return {"strategies": strategies, "schemes": schemes}


def _strip_nulls(obj):
    """Recursively remove keys with None/null values from dicts."""
    if isinstance(obj, dict):
        return {k: _strip_nulls(v) for k, v in obj.items() if v is not None}
    elif isinstance(obj, list):
        return [_strip_nulls(item) for item in obj]
    return obj


def _strip_action_category(actions: list[dict]) -> list[dict]:
    """Remove redundant 'category' field from action dicts."""
    for act in actions:
        act.pop("category", None)
        # Also strip from triggers if present (shouldn't be, but defensive)
    return actions


def export_knowledge_base(models: list[dict], crew_cards: list[dict],
                          upgrades: list[dict], markers: list[dict],
                          tokens: list[dict], faction_summary: dict,
                          rules: list[dict] = None, faq: list[dict] = None,
                          gaining_grounds: dict = None) -> dict:
    """Build a single combined JSON knowledge base optimized for AI consumption.

    Strips redundant fields:
    - action.category (redundant with parent array name)
    - marker.terrain_traits_csv (redundant with terrain_traits array)
    - All null values
    """
    import copy
    from datetime import date

    # Deep copy to avoid mutating the originals used by other exports
    kb_models = copy.deepcopy(models)
    kb_crew = copy.deepcopy(crew_cards)
    kb_upgrades = copy.deepcopy(upgrades)
    kb_markers = copy.deepcopy(markers)

    # Strip redundant action.category from models
    for m in kb_models:
        _strip_action_category(m.get("attack_actions", []))
        _strip_action_category(m.get("tactical_actions", []))

    # Strip redundant action.category from crew card keyword actions
    for cc in kb_crew:
        for ka in cc.get("keyword_actions", []):
            for act in ka.get("actions", []):
                act.pop("category", None)

    # Strip redundant action.category from upgrades
    for u in kb_upgrades:
        _strip_action_category(u.get("granted_actions", []))

    # Strip redundant terrain_traits_csv from markers
    for mk in kb_markers:
        mk.pop("terrain_traits_csv", None)

    # Build the combined knowledge base
    counts = {
        "models": len(kb_models),
        "crew_cards": len(kb_crew),
        "upgrades": len(kb_upgrades),
        "markers": len(kb_markers),
        "tokens": len(tokens),
    }

    kb = {
        "_meta": {
            "description": "Malifaux 4th Edition complete game data — "
                           "models, crew cards, upgrades, rules, FAQ, and Gaining Grounds",
            "generated": date.today().isoformat(),
            "counts": counts,
        },
        "models": _strip_nulls(kb_models),
        "crew_cards": _strip_nulls(kb_crew),
        "upgrades": _strip_nulls(kb_upgrades),
        "markers": _strip_nulls(kb_markers),
        "tokens": _strip_nulls(tokens),
        "faction_summary": faction_summary,
    }

    if rules is not None:
        kb["rules"] = _strip_nulls(rules)
        counts["rules_sections"] = len(rules)
    if faq is not None:
        kb["faq"] = _strip_nulls(faq)
        counts["faq_entries"] = len(faq)
    if gaining_grounds is not None:
        kb["strategies"] = _strip_nulls(gaining_grounds["strategies"])
        kb["schemes"] = _strip_nulls(gaining_grounds["schemes"])
        counts["strategies"] = len(gaining_grounds["strategies"])
        counts["schemes"] = len(gaining_grounds["schemes"])

    return kb


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

    # Gather all data
    print("Exporting models...")
    all_models = export_models(conn)
    print(f"  {len(all_models)} models")

    print("Exporting crew cards...")
    all_crew = export_crew_cards(conn)
    print(f"  {len(all_crew)} crew cards")

    print("Exporting upgrades...")
    all_upgrades = export_upgrades(conn)
    print(f"  {len(all_upgrades)} upgrades")

    print("Exporting tokens...")
    tokens = export_token_registry(conn)
    print(f"  {len(tokens)} tokens")

    print("Exporting markers...")
    markers = export_marker_registry(conn)
    print(f"  {len(markers)} markers")

    print("Exporting rules...")
    all_rules = export_rules(conn)
    print(f"  {len(all_rules)} sections")

    print("Exporting FAQ...")
    all_faq = export_faq(conn)
    print(f"  {len(all_faq)} entries")

    print("Exporting Gaining Grounds...")
    gg = export_gaining_grounds(conn)
    print(f"  {len(gg['strategies'])} strategies, {len(gg['schemes'])} schemes")

    summary = build_faction_summary(all_models)

    # Build single combined knowledge base
    print("\nBuilding knowledge base...")
    kb = export_knowledge_base(all_models, all_crew, all_upgrades, markers, tokens, summary,
                               rules=all_rules, faq=all_faq, gaining_grounds=gg)
    kb_path = OUT_DIR / "m4e_knowledge_base.json"
    with open(kb_path, "w", encoding="utf-8") as f:
        json.dump(kb, f, indent=2, ensure_ascii=False)

    kb_size = kb_path.stat().st_size / 1024
    size_str = f"{kb_size/1024:.1f} MB" if kb_size > 1024 else f"{kb_size:.0f} KB"

    # Stats
    total_abilities = sum(len(m.get("abilities", [])) for m in all_models)
    total_actions = sum(
        len(m.get("attack_actions", [])) + len(m.get("tactical_actions", []))
        for m in all_models
    )
    total_triggers = sum(
        len(a.get("triggers", []))
        for m in all_models
        for a in m.get("attack_actions", []) + m.get("tactical_actions", [])
    )

    by_faction = defaultdict(int)
    for m in all_models:
        by_faction[m["faction"]] += 1

    print(f"\n{'='*50}")
    print(f"EXPORT COMPLETE -> {kb_path.name} ({size_str})")
    print(f"{'='*50}")
    print(f"  Models:       {len(all_models)}")
    print(f"  Crew Cards:   {len(all_crew)}")
    print(f"  Upgrades:     {len(all_upgrades)}")
    print(f"  Abilities:    {total_abilities}")
    print(f"  Actions:      {total_actions}")
    print(f"  Triggers:     {total_triggers}")
    print(f"  Tokens:       {len(tokens)}")
    print(f"  Markers:      {len(markers)}")
    print(f"  Rules:        {len(all_rules)} sections")
    print(f"  FAQ:          {len(all_faq)} entries")
    print(f"  Strategies:   {len(gg['strategies'])}")
    print(f"  Schemes:      {len(gg['schemes'])}")
    print(f"  Factions:     {len(by_faction)}")

    conn.close()


if __name__ == "__main__":
    main()
