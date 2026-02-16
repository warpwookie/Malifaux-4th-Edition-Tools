"""
patch_upgrades.py — Add upgrade card support to the M4E pipeline.

Patches: card_extractor.py, db_loader.py, pipeline.py, schema.sql
Also creates: prompts/upgrade_prompt.txt
Also runs: ALTER TABLE on existing database

Usage:
    python patch_upgrades.py              # Preview changes
    python patch_upgrades.py --apply      # Apply patches
"""
import sys
import sqlite3
from pathlib import Path

DRY_RUN = "--apply" not in sys.argv

# ============================================================
# 1. SCHEMA — Add upgrade tables to existing DB
# ============================================================
UPGRADE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS upgrades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    upgrade_type    TEXT,
    keyword         TEXT,
    faction         TEXT,
    limitations     TEXT,
    description     TEXT,
    source_pdf      TEXT,
    parse_date      TEXT,
    parse_status    TEXT DEFAULT 'auto'
);

CREATE TABLE IF NOT EXISTS upgrade_abilities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    upgrade_id      INTEGER NOT NULL,
    name            TEXT NOT NULL,
    defensive_type  TEXT,
    text            TEXT NOT NULL,
    FOREIGN KEY (upgrade_id) REFERENCES upgrades(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS upgrade_actions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    upgrade_id              INTEGER NOT NULL,
    name                    TEXT NOT NULL,
    category                TEXT NOT NULL,
    action_type             TEXT,
    range                   TEXT,
    skill_value             INTEGER,
    skill_built_in_suit     TEXT,
    skill_fate_modifier     TEXT,
    resist                  TEXT,
    tn                      INTEGER,
    damage                  TEXT,
    is_signature            BOOLEAN DEFAULT 0,
    soulstone_cost          INTEGER DEFAULT 0,
    effects                 TEXT,
    costs_and_restrictions  TEXT,
    FOREIGN KEY (upgrade_id) REFERENCES upgrades(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS upgrade_action_triggers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id       INTEGER NOT NULL,
    name            TEXT NOT NULL,
    suit            TEXT,
    timing          TEXT,
    text            TEXT NOT NULL,
    is_mandatory    BOOLEAN DEFAULT 0,
    soulstone_cost  INTEGER DEFAULT 0,
    FOREIGN KEY (action_id) REFERENCES upgrade_actions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_upgrades_keyword ON upgrades(keyword);
CREATE INDEX IF NOT EXISTS idx_upgrades_faction ON upgrades(faction);
CREATE INDEX IF NOT EXISTS idx_upgrade_abilities_upgrade ON upgrade_abilities(upgrade_id);
CREATE INDEX IF NOT EXISTS idx_upgrade_actions_upgrade ON upgrade_actions(upgrade_id);
"""

# ============================================================
# 2. CARD EXTRACTOR — Add extract_upgrade_card function
# ============================================================
EXTRACTOR_ADDITION = '''

def extract_upgrade_card(client: anthropic.Anthropic, image_path: str) -> dict:
    """
    Extract an upgrade card from a single image.
    Returns parsed JSON dict or {"error": str}.
    """
    prompt = load_prompt("upgrade_prompt")
    print(f"  Extracting upgrade card: {Path(image_path).name}")
    
    img_data, media_type = image_to_base64(image_path)
    
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_data}},
                        {"type": "text", "text": prompt}
                    ]
                }]
            )
            
            text = response.content[0].text
            # Strip markdown fences
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            return json.loads(text.strip())
        
        except json.JSONDecodeError as e:
            if attempt < RETRY_ATTEMPTS - 1:
                print(f"    JSON parse error, retrying ({attempt+1}/{RETRY_ATTEMPTS})...")
                time.sleep(RETRY_DELAY)
            else:
                return {"error": f"JSON parse failed after {RETRY_ATTEMPTS} attempts: {e}"}
        
        except Exception as e:
            if attempt < RETRY_ATTEMPTS - 1:
                print(f"    API error, retrying ({attempt+1}/{RETRY_ATTEMPTS})...")
                time.sleep(RETRY_DELAY)
            else:
                return {"error": f"API call failed: {e}"}
'''

# ============================================================
# 3. DB LOADER — Add load_upgrade_card function
# ============================================================
LOADER_ADDITION = '''

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
    
    # Abilities
    for ab in card.get("granted_abilities", []):
        c.execute("""INSERT INTO upgrade_abilities (upgrade_id, name, defensive_type, text)
            VALUES (?,?,?,?)""",
            (upgrade_id, ab["name"], ab.get("defensive_type"), ab["text"]))
    
    # Actions
    for act in card.get("granted_actions", []):
        c.execute("""INSERT INTO upgrade_actions 
            (upgrade_id, name, category, action_type, range, skill_value,
             skill_built_in_suit, skill_fate_modifier, resist, tn, damage,
             is_signature, soulstone_cost, effects, costs_and_restrictions)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (upgrade_id, act["name"], act.get("category", "tactical_actions"),
             act.get("action_type"), act.get("range"), act.get("skill_value"),
             act.get("skill_built_in_suit"), act.get("skill_fate_modifier"),
             act.get("resist"), act.get("tn"), act.get("damage"),
             act.get("is_signature", False), act.get("soulstone_cost", 0),
             act.get("effects"), act.get("costs_and_restrictions")))
        action_id = c.lastrowid
        for trig in act.get("triggers", []):
            c.execute("""INSERT INTO upgrade_action_triggers
                (action_id, name, suit, timing, text, is_mandatory, soulstone_cost)
                VALUES (?,?,?,?,?,?,?)""",
                (action_id, trig["name"], trig.get("suit"), trig.get("timing"),
                 trig["text"], trig.get("is_mandatory", False), trig.get("soulstone_cost", 0)))
    
    conn.commit()
    return {"status": status, "upgrade_id": upgrade_id, "name": name}
'''

# ============================================================
# APPLY PATCHES
# ============================================================

def patch_file(filepath, marker_text, insert_before, new_content, description):
    """Insert new_content before a marker line in a file."""
    p = Path(filepath)
    text = p.read_text(encoding="utf-8")
    
    if marker_text in text and new_content.strip().split("\n")[2] in text:
        print(f"  SKIP {filepath}: already patched ({description})")
        return False
    
    if insert_before:
        if insert_before not in text:
            print(f"  ERROR {filepath}: can't find insertion point '{insert_before[:50]}...'")
            return False
        text = text.replace(insert_before, new_content + "\n" + insert_before)
    else:
        # Append to end
        text = text.rstrip() + "\n" + new_content + "\n"
    
    if not DRY_RUN:
        p.write_text(text, encoding="utf-8")
    print(f"  {'WOULD PATCH' if DRY_RUN else 'PATCHED'} {filepath}: {description}")
    return True


def main():
    print("=" * 60)
    print("Patching M4E pipeline for upgrade card support")
    print("=" * 60)
    
    # 1. Apply schema to database
    print("\n[1/6] Database schema...")
    db_path = "db/m4e.db"
    if not DRY_RUN:
        conn = sqlite3.connect(db_path)
        conn.executescript(UPGRADE_SCHEMA_SQL)
        conn.close()
        print(f"  APPLIED upgrade tables to {db_path}")
    else:
        print(f"  WOULD CREATE 4 new tables + 4 indexes in {db_path}")
    
    # 2. Also add to schema.sql for fresh installs
    print("\n[2/6] schema.sql...")
    schema_addition = """
-- ============================================================
-- UPGRADE CARDS
-- ============================================================

CREATE TABLE IF NOT EXISTS upgrades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    upgrade_type    TEXT,                                -- e.g., "Loot", "Training"
    keyword         TEXT,                                -- Keyword this upgrade belongs to
    faction         TEXT,
    limitations     TEXT,                                -- e.g., "Plentiful", "Restricted"
    description     TEXT,                                -- Intro text
    source_pdf      TEXT,
    parse_date      TEXT,
    parse_status    TEXT DEFAULT 'auto'
);

CREATE TABLE IF NOT EXISTS upgrade_abilities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    upgrade_id      INTEGER NOT NULL,
    name            TEXT NOT NULL,
    defensive_type  TEXT,
    text            TEXT NOT NULL,
    FOREIGN KEY (upgrade_id) REFERENCES upgrades(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS upgrade_actions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    upgrade_id              INTEGER NOT NULL,
    name                    TEXT NOT NULL,
    category                TEXT NOT NULL,
    action_type             TEXT,
    range                   TEXT,
    skill_value             INTEGER,
    skill_built_in_suit     TEXT,
    skill_fate_modifier     TEXT,
    resist                  TEXT,
    tn                      INTEGER,
    damage                  TEXT,
    is_signature            BOOLEAN DEFAULT 0,
    soulstone_cost          INTEGER DEFAULT 0,
    effects                 TEXT,
    costs_and_restrictions  TEXT,
    FOREIGN KEY (upgrade_id) REFERENCES upgrades(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS upgrade_action_triggers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id       INTEGER NOT NULL,
    name            TEXT NOT NULL,
    suit            TEXT,
    timing          TEXT,
    text            TEXT NOT NULL,
    is_mandatory    BOOLEAN DEFAULT 0,
    soulstone_cost  INTEGER DEFAULT 0,
    FOREIGN KEY (action_id) REFERENCES upgrade_actions(id) ON DELETE CASCADE
);
"""
    schema_idx = """
CREATE INDEX IF NOT EXISTS idx_upgrades_keyword ON upgrades(keyword);
CREATE INDEX IF NOT EXISTS idx_upgrades_faction ON upgrades(faction);
CREATE INDEX IF NOT EXISTS idx_upgrade_abilities_upgrade ON upgrade_abilities(upgrade_id);
CREATE INDEX IF NOT EXISTS idx_upgrade_actions_upgrade ON upgrade_actions(upgrade_id);
"""
    # Insert upgrade tables before TOKEN REFERENCE section, indexes at end
    patch_file("db/schema.sql",
               "upgrades",
               "-- ============================================================\n-- TOKEN REFERENCE",
               schema_addition,
               "add upgrade tables")
    
    # Append indexes
    schema_text = Path("db/schema.sql").read_text(encoding="utf-8")
    if "idx_upgrades_keyword" not in schema_text:
        if not DRY_RUN:
            with open("db/schema.sql", "a", encoding="utf-8") as f:
                f.write(schema_idx)
        print(f"  {'WOULD APPEND' if DRY_RUN else 'APPENDED'} db/schema.sql: upgrade indexes")
    
    # 3. Create upgrade prompt
    print("\n[3/6] Upgrade prompt...")
    prompt_path = Path("prompts/upgrade_prompt.txt")
    if prompt_path.exists():
        print(f"  SKIP {prompt_path}: already exists")
    else:
        if not DRY_RUN:
            prompt_path.write_text(Path("/home/claude/upgrade_prompt.txt" if Path("/home/claude/upgrade_prompt.txt").exists() else "upgrade_prompt.txt").read_text(encoding="utf-8") if False else UPGRADE_PROMPT_TEXT, encoding="utf-8")
        print(f"  {'WOULD CREATE' if DRY_RUN else 'CREATED'} {prompt_path}")
    
    # 4. Patch card_extractor.py
    print("\n[4/6] card_extractor.py...")
    ext_path = Path("scripts/card_extractor.py")
    ext_text = ext_path.read_text(encoding="utf-8")
    if "extract_upgrade_card" in ext_text:
        print(f"  SKIP {ext_path}: already has extract_upgrade_card")
    else:
        if not DRY_RUN:
            ext_text = ext_text.rstrip() + "\n" + EXTRACTOR_ADDITION + "\n"
            ext_path.write_text(ext_text, encoding="utf-8")
        print(f"  {'WOULD PATCH' if DRY_RUN else 'PATCHED'} {ext_path}: add extract_upgrade_card()")
    
    # 5. Patch db_loader.py
    print("\n[5/6] db_loader.py...")
    loader_path = Path("scripts/db_loader.py")
    loader_text = loader_path.read_text(encoding="utf-8")
    if "load_upgrade_card" in loader_text:
        print(f"  SKIP {loader_path}: already has load_upgrade_card")
    else:
        # Insert before log_parse function
        marker = "def log_parse("
        if marker in loader_text:
            if not DRY_RUN:
                loader_text = loader_text.replace(marker, LOADER_ADDITION + "\n\n" + marker)
                loader_path.write_text(loader_text, encoding="utf-8")
            print(f"  {'WOULD PATCH' if DRY_RUN else 'PATCHED'} {loader_path}: add load_upgrade_card()")
        else:
            print(f"  ERROR {loader_path}: can't find insertion point")
        
        # Also update the import in the __main__ block to handle upgrade cards
        if not DRY_RUN:
            loader_text = loader_path.read_text(encoding="utf-8")
            # Add upgrade card routing
            old_routing = '''        if card_type == "crew_card":
            result = load_crew_card(conn, card, args.replace)
        else:
            result = load_stat_card(conn, card, args.replace)'''
            new_routing = '''        if card_type == "crew_card":
            result = load_crew_card(conn, card, args.replace)
        elif card_type == "upgrade":
            result = load_upgrade_card(conn, card, args.replace)
        else:
            result = load_stat_card(conn, card, args.replace)'''
            if old_routing in loader_text:
                loader_text = loader_text.replace(old_routing, new_routing)
                loader_path.write_text(loader_text, encoding="utf-8")
                print(f"  PATCHED {loader_path}: add upgrade routing in __main__")
            
            # Add upgrade count to summary
            old_summary = '''    c.execute("SELECT COUNT(*) FROM crew_cards")
    print(f"          {c.fetchone()[0]} crew cards total")'''
            new_summary = '''    c.execute("SELECT COUNT(*) FROM crew_cards")
    print(f"          {c.fetchone()[0]} crew cards total")
    try:
        c.execute("SELECT COUNT(*) FROM upgrades")
        print(f"          {c.fetchone()[0]} upgrade cards total")
    except:
        pass'''
            if old_summary in loader_text:
                loader_text = loader_text.replace(old_summary, new_summary)
                loader_path.write_text(loader_text, encoding="utf-8")
                print(f"  PATCHED {loader_path}: add upgrade count in summary")
    
    # 6. Patch pipeline.py
    print("\n[6/6] pipeline.py...")
    pipe_path = Path("scripts/pipeline.py")
    pipe_text = pipe_path.read_text(encoding="utf-8")
    if "upgrade_card" in pipe_text and "extract_upgrade_card" in pipe_text:
        print(f"  SKIP {pipe_path}: already has upgrade support")
    else:
        changes = 0
        
        # a) Add import
        old_import = "from card_extractor import extract_stat_card, extract_crew_card"
        new_import = "from card_extractor import extract_stat_card, extract_crew_card, extract_upgrade_card"
        if old_import in pipe_text and "extract_upgrade_card" not in pipe_text:
            pipe_text = pipe_text.replace(old_import, new_import)
            changes += 1
        
        # b) Add load_upgrade_card import
        old_loader_import = "from db_loader import init_db, load_stat_card, load_crew_card, log_parse"
        new_loader_import = "from db_loader import init_db, load_stat_card, load_crew_card, load_upgrade_card, log_parse"
        if old_loader_import in pipe_text:
            pipe_text = pipe_text.replace(old_loader_import, new_loader_import)
            changes += 1
        
        # c) Add upgrade_card processing branch in process_single_pdf
        old_crew_block = '''    elif card_type == "crew_card":
        img = images[0]
        merged = extract_crew_card(client, img["image_path"])
        if "error" in merged:
            return {"status": "error", "step": "vision", "error": merged["error"]}
        merged["source_pdf"] = str(pdf_path)
    
    else:'''
        new_crew_block = '''    elif card_type == "crew_card":
        img = images[0]
        merged = extract_crew_card(client, img["image_path"])
        if "error" in merged:
            return {"status": "error", "step": "vision", "error": merged["error"]}
        merged["source_pdf"] = str(pdf_path)
    
    elif card_type == "upgrade_card":
        img = images[0]
        merged = extract_upgrade_card(client, img["image_path"])
        if "error" in merged:
            return {"status": "error", "step": "vision", "error": merged["error"]}
        merged["source_pdf"] = str(pdf_path)
    
    else:'''
        if old_crew_block in pipe_text:
            pipe_text = pipe_text.replace(old_crew_block, new_crew_block)
            changes += 1
        
        # d) Add upgrade_card DB load routing
        old_load = '''        if card_type == "crew_card":
            load_result = load_crew_card(conn, merged, replace)
        else:
            load_result = load_stat_card(conn, merged, replace)'''
        new_load = '''        if card_type == "crew_card":
            load_result = load_crew_card(conn, merged, replace)
        elif card_type == "upgrade_card":
            load_result = load_upgrade_card(conn, merged, replace)
        else:
            load_result = load_stat_card(conn, merged, replace)'''
        if old_load in pipe_text:
            pipe_text = pipe_text.replace(old_load, new_load)
            changes += 1
        
        if changes > 0 and not DRY_RUN:
            pipe_path.write_text(pipe_text, encoding="utf-8")
        print(f"  {'WOULD PATCH' if DRY_RUN else 'PATCHED'} {pipe_path}: {changes} changes for upgrade support")
    
    print("\n" + "=" * 60)
    if DRY_RUN:
        print("DRY RUN complete. Use --apply to make changes.")
    else:
        print("All patches applied! Ready to process upgrade cards.")
    print("=" * 60)


# Upgrade prompt text (embedded so we don't depend on external file)
UPGRADE_PROMPT_TEXT = """You are a precise data extraction engine for Malifaux 4th Edition upgrade cards. Upgrade cards grant abilities and/or actions to models that attach the upgrade during the game. Extract ALL data into the JSON structure below.

## UPGRADE CARD LAYOUT
- Top: Upgrade name and type (e.g., "Loot")
- Limitations line (if any): e.g., "Plentiful", "Restricted: [keyword]"
- Body: Description text, then granted abilities and/or actions
- Abilities appear as named blocks with rules text
- Actions appear with the standard stat line (action type, range, skill, resist/TN, damage)
- Actions may have triggers listed below them

## TEXT RENDERING RULES
Same icon substitutions as stat cards:
- Suits: (r) = Ram, (m) = Mask, (t) = Tome, (c) = Crow
- Range types: (melee), (gun), (magic), (aura), (pulse)
- Soulstone: (soulstone) or (ss)
- Fate modifiers: (+), (-)
- Action markers: act = general action, sig = signature action (f/F icon)
- Defensive icons: (fortitude), (warding)

## ACTION PARSING RULES
Attack actions have: action_type (melee/missile/magic/variable), range, skill vs resist, damage
Tactical actions have: TN (target number) or no stat line, no resist, no damage
- If an action has a Rg column with y/z/q/* icon \\u2192 attack action
- If an action has a TN column \\u2192 tactical action
- "costs_and_restrictions" = italic text before effects (declaration-phase requirements)
- "effects" = the main resolution text

## TRIGGER RULES
- Each trigger has: suit requirement, timing keyword, name, effect text
- Timing keywords: "When Resolving", "After Succeeding", "After Failing", "After Damaging", "When Declaring", "After Resolving"
- Map to: "when_resolving", "after_succeeding", "after_failing", "after_damaging", "when_declaring", "after_resolving"
- If no timing keyword appears, default to "after_succeeding"
- Mandatory triggers have a star/asterisk before the name
- (soulstone) or (ss) before trigger name means soulstone_cost = 1 (or 2 for double)

## OUTPUT FORMAT
Respond with ONLY this JSON:

```json
{
  "card_type": "upgrade",
  "name": "string \\u2014 Upgrade name exactly as printed",
  "upgrade_type": "string \\u2014 e.g., 'Loot', 'Training', etc. Null if not shown.",
  "limitations": "string or null \\u2014 e.g., 'Plentiful', 'Restricted: Freikorps'. Null if none.",
  "description": "string or null \\u2014 Introductory/flavor text about the upgrade. Null if none.",
  "granted_abilities": [
    {
      "name": "string \\u2014 ability name",
      "defensive_type": "fortitude|warding|unusual_defense|null",
      "text": "string \\u2014 full ability rules text with icon substitutions"
    }
  ],
  "granted_actions": [
    {
      "name": "string \\u2014 action name",
      "category": "attack_actions|tactical_actions",
      "action_type": "melee|missile|magic|variable|null",
      "range": "string or null \\u2014 e.g., '(melee)1\\\"', '(gun)12\\\"', '(aura)6\\\"'",
      "skill_value": "integer or null",
      "skill_built_in_suit": "string or null \\u2014 e.g., '(r)', '(m)', '(t)', '(c)'",
      "skill_fate_modifier": "string or null \\u2014 '+' or '-'",
      "resist": "string or null \\u2014 'Df', 'Wp', etc.",
      "tn": "integer or null \\u2014 target number for tactical actions",
      "damage": "string or null \\u2014 e.g., '2', '3/4/5'",
      "is_signature": false,
      "soulstone_cost": 0,
      "costs_and_restrictions": "string or null \\u2014 italic declaration text",
      "effects": "string or null \\u2014 resolution effect text",
      "triggers": [
        {
          "name": "string",
          "suit": "string \\u2014 e.g., '(r)', '(m)(m)', '(c)(t)'",
          "timing": "when_resolving|after_succeeding|after_failing|after_damaging|when_declaring|after_resolving",
          "text": "string \\u2014 full trigger effect text",
          "is_mandatory": false,
          "soulstone_cost": 0
        }
      ]
    }
  ],
  "extraction_notes": []
}
```
"""


if __name__ == "__main__":
    main()
