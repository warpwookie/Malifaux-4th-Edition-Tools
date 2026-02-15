"""
patch_upgrades_v2.py — Add upgrade card support to Python scripts + prompt.

Step 1 (DB tables) already applied. This handles the rest:
- Creates prompts/upgrade_prompt.txt
- Patches scripts/card_extractor.py
- Patches scripts/db_loader.py  
- Patches scripts/pipeline.py

Usage:
    python patch_upgrades_v2.py              # Preview
    python patch_upgrades_v2.py --apply      # Apply
"""
import sys
from pathlib import Path

DRY_RUN = "--apply" not in sys.argv

def patch_replace(filepath, old, new, label):
    p = Path(filepath)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        if new.strip()[:40] in text:
            print(f"  SKIP {filepath}: already patched ({label})")
        else:
            print(f"  ERROR {filepath}: can't find target for '{label}'")
        return
    if not DRY_RUN:
        text = text.replace(old, new)
        p.write_text(text, encoding="utf-8")
    print(f"  {'WOULD PATCH' if DRY_RUN else 'PATCHED'} {filepath}: {label}")

def patch_append(filepath, content, marker, label):
    p = Path(filepath)
    text = p.read_text(encoding="utf-8")
    if marker in text:
        print(f"  SKIP {filepath}: already has {label}")
        return
    if not DRY_RUN:
        text = text.rstrip() + "\n" + content + "\n"
        p.write_text(text, encoding="utf-8")
    print(f"  {'WOULD APPEND' if DRY_RUN else 'APPENDED'} {filepath}: {label}")

print("=" * 60)
print("Patching M4E pipeline for upgrade card support (v2)")
print("=" * 60)

# ============================================================
# 1. Create prompts/upgrade_prompt.txt
# ============================================================
print("\n[1/4] Upgrade prompt...")
prompt_path = Path("prompts/upgrade_prompt.txt")
if prompt_path.exists():
    print(f"  SKIP: {prompt_path} already exists")
else:
    PROMPT = r'''You are a precise data extraction engine for Malifaux 4th Edition upgrade cards. Upgrade cards grant abilities and/or actions to models that attach the upgrade during the game. Extract ALL data into the JSON structure below.

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
- If an action has a Rg column with y/z/q/* icon — attack action
- If an action has a TN column — tactical action
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
  "name": "string — Upgrade name exactly as printed",
  "upgrade_type": "string — e.g., 'Loot', 'Training', etc. Null if not shown.",
  "limitations": "string or null — e.g., 'Plentiful', 'Restricted: Freikorps'. Null if none.",
  "description": "string or null — Introductory/flavor text about the upgrade. Null if none.",
  "granted_abilities": [
    {
      "name": "string — ability name",
      "defensive_type": "fortitude|warding|unusual_defense|null",
      "text": "string — full ability rules text with icon substitutions"
    }
  ],
  "granted_actions": [
    {
      "name": "string — action name",
      "category": "attack_actions|tactical_actions",
      "action_type": "melee|missile|magic|variable|null",
      "range": "string or null",
      "skill_value": "integer or null",
      "skill_built_in_suit": "string or null",
      "skill_fate_modifier": "string or null",
      "resist": "string or null",
      "tn": "integer or null",
      "damage": "string or null",
      "is_signature": false,
      "soulstone_cost": 0,
      "costs_and_restrictions": "string or null",
      "effects": "string or null",
      "triggers": [
        {
          "name": "string",
          "suit": "string",
          "timing": "when_resolving|after_succeeding|after_failing|after_damaging|when_declaring|after_resolving",
          "text": "string",
          "is_mandatory": false,
          "soulstone_cost": 0
        }
      ]
    }
  ],
  "extraction_notes": []
}
```
'''
    if not DRY_RUN:
        prompt_path.parent.mkdir(exist_ok=True)
        prompt_path.write_text(PROMPT, encoding="utf-8")
    print(f"  {'WOULD CREATE' if DRY_RUN else 'CREATED'} {prompt_path}")

# ============================================================
# 2. Patch card_extractor.py — add extract_upgrade_card()
# ============================================================
print("\n[2/4] card_extractor.py...")

EXTRACTOR_FN = '''

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

patch_append("scripts/card_extractor.py", EXTRACTOR_FN, "extract_upgrade_card", "extract_upgrade_card()")

# ============================================================
# 3. Patch db_loader.py — add load_upgrade_card()
# ============================================================
print("\n[3/4] db_loader.py...")

LOADER_FN = '''

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
    
    for ab in card.get("granted_abilities", []):
        c.execute("""INSERT INTO upgrade_abilities (upgrade_id, name, defensive_type, text)
            VALUES (?,?,?,?)""",
            (upgrade_id, ab["name"], ab.get("defensive_type"), ab["text"]))
    
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

patch_append("scripts/db_loader.py", LOADER_FN, "load_upgrade_card", "load_upgrade_card()")

# Also patch the __main__ routing
patch_replace("scripts/db_loader.py",
    '''        if card_type == "crew_card":
            result = load_crew_card(conn, card, args.replace)
        else:
            result = load_stat_card(conn, card, args.replace)''',
    '''        if card_type == "crew_card":
            result = load_crew_card(conn, card, args.replace)
        elif card_type == "upgrade":
            result = load_upgrade_card(conn, card, args.replace)
        else:
            result = load_stat_card(conn, card, args.replace)''',
    "upgrade routing in __main__")

# ============================================================
# 4. Patch pipeline.py — add upgrade card branch
# ============================================================
print("\n[4/4] pipeline.py...")

# Import
patch_replace("scripts/pipeline.py",
    "from card_extractor import extract_stat_card, extract_crew_card",
    "from card_extractor import extract_stat_card, extract_crew_card, extract_upgrade_card",
    "import extract_upgrade_card")

patch_replace("scripts/pipeline.py",
    "from db_loader import init_db, load_stat_card, load_crew_card, log_parse",
    "from db_loader import init_db, load_stat_card, load_crew_card, load_upgrade_card, log_parse",
    "import load_upgrade_card")

# Processing branch
patch_replace("scripts/pipeline.py",
    '''    elif card_type == "crew_card":
        img = images[0]
        merged = extract_crew_card(client, img["image_path"])
        if "error" in merged:
            return {"status": "error", "step": "vision", "error": merged["error"]}
        merged["source_pdf"] = str(pdf_path)
    
    else:''',
    '''    elif card_type == "crew_card":
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
    
    else:''',
    "upgrade extraction branch")

# DB load routing
patch_replace("scripts/pipeline.py",
    '''        if card_type == "crew_card":
            load_result = load_crew_card(conn, merged, replace)
        else:
            load_result = load_stat_card(conn, merged, replace)''',
    '''        if card_type == "crew_card":
            load_result = load_crew_card(conn, merged, replace)
        elif card_type == "upgrade_card":
            load_result = load_upgrade_card(conn, merged, replace)
        else:
            load_result = load_stat_card(conn, merged, replace)''',
    "upgrade DB load routing")

# Done
print("\n" + "=" * 60)
if DRY_RUN:
    print("DRY RUN complete. Use --apply to make changes.")
else:
    print("All patches applied! Ready to process upgrade cards.")
print("=" * 60)
