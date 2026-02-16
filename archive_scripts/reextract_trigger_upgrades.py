"""
reextract_trigger_upgrades.py — Re-extract the 5 upgrade cards that grant triggers.

These cards don't grant abilities or actions — they grant triggers that attach
to a model's existing actions. Uses a targeted prompt to capture this pattern.

Usage:
    python reextract_trigger_upgrades.py              # Preview
    python reextract_trigger_upgrades.py --apply      # Extract + load
"""
import base64
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from datetime import datetime

DRY_RUN = "--apply" not in sys.argv
DB_PATH = "db/m4e.db"

try:
    import anthropic
except ImportError:
    print("ERROR: pip install anthropic")
    sys.exit(1)

MODEL = "claude-sonnet-4-5-20250929"

TRIGGER_PROMPT = """You are a precise data extraction engine for Malifaux 4th Edition upgrade cards.

This upgrade card grants TRIGGERS (not abilities or actions) to a model's existing actions. Extract the trigger data.

## TEXT RENDERING RULES
- Suits: (r) = Ram, (m) = Mask, (t) = Tome, (c) = Crow
- Fate modifiers: (+), (-)
- Soulstone: (soulstone) or (ss)

## TRIGGER RULES
- Each trigger has: suit requirement, timing keyword, name, effect text
- Timing keywords: "When Resolving", "After Succeeding", "After Failing", "After Damaging", "When Declaring", "After Resolving"
- Map to: "when_resolving", "after_succeeding", "after_failing", "after_damaging", "when_declaring", "after_resolving"
- If no timing keyword appears, default to "after_succeeding"
- Mandatory triggers have a star/asterisk (*) before the name

## OUTPUT FORMAT
Respond with ONLY this JSON:

```json
{
  "card_type": "upgrade",
  "name": "string — Upgrade name exactly as printed",
  "upgrade_type": "string or null",
  "limitations": "string or null",
  "description": "string or null — any intro text before the triggers",
  "granted_triggers": [
    {
      "name": "string — trigger name",
      "suit": "string — e.g., '(r)', '(m)(c)', '(t)'",
      "timing": "when_resolving|after_succeeding|after_failing|after_damaging|when_declaring|after_resolving",
      "text": "string — full trigger effect text",
      "is_mandatory": false,
      "soulstone_cost": 0,
      "applies_to": "string — e.g., 'all attack actions', 'all actions printed on its stat card'"
    }
  ],
  "extraction_notes": []
}
```
"""


def main():
    print("=" * 60)
    print("Re-extracting trigger-granting upgrades")
    print("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Get the 5 flagged upgrades
    c.execute("""SELECT u.id, u.name, u.source_pdf, u.keyword, u.faction 
                 FROM upgrades u WHERE u.parse_status='flagged'""")
    flagged = c.fetchall()
    
    print(f"Found {len(flagged)} flagged upgrades\n")
    
    if DRY_RUN:
        for uid, name, src, kw, faction in flagged:
            print(f"  id={uid} {name} [{faction}/{kw}]")
            print(f"    Source: {src}")
        print(f"\nDry run — use --apply to re-extract.")
        conn.close()
        return
    
    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY")
        sys.exit(1)
    
    client = anthropic.Anthropic(api_key=api_key)
    
    for i, (uid, name, src, kw, faction) in enumerate(flagged):
        print(f"[{i+1}/{len(flagged)}] {name}")
        print(f"  Source: {src}")
        
        src_path = Path(src)
        if not src_path.exists():
            print(f"  ERROR: Source PDF not found")
            continue
        
        # Extract image from PDF
        work_dir = Path("pipeline_work") / src_path.stem
        work_dir.mkdir(parents=True, exist_ok=True)
        
        # Find existing extracted image
        front_img = work_dir / f"{src_path.stem}_front.png"
        if not front_img.exists():
            # Re-extract
            sys.path.insert(0, str(Path("scripts")))
            from pdf_splitter import extract_card_images
            images = extract_card_images(str(src_path), str(work_dir))
            if images:
                front_img = Path(images[0]["image_path"])
            else:
                print(f"  ERROR: Could not extract image")
                continue
        
        # Send to API
        print(f"  Extracting with trigger-aware prompt...")
        with open(front_img, "rb") as f:
            img_data = base64.standard_b64encode(f.read()).decode("utf-8")
        
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_data}},
                        {"type": "text", "text": TRIGGER_PROMPT}
                    ]
                }]
            )
            
            text = response.content[0].text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            card = json.loads(text.strip())
            
            # Save JSON
            json_path = work_dir / f"{src_path.stem}_triggers.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(card, f, indent=2, ensure_ascii=False)
            
            triggers = card.get("granted_triggers", [])
            print(f"  Found {len(triggers)} granted triggers")
            
            for trig in triggers:
                print(f"    {trig.get('suit', '?')} {trig['name']} ({trig.get('timing', '?')})")
                print(f"      applies_to: {trig.get('applies_to', '?')}")
                print(f"      text: {trig.get('text', '')[:80]}...")
            
            # Load to upgrade_granted_triggers table
            for trig in triggers:
                c.execute("""INSERT INTO upgrade_granted_triggers
                    (upgrade_id, name, suit, timing, text, is_mandatory, soulstone_cost, applies_to)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (uid, trig["name"], trig.get("suit"), trig.get("timing"),
                     trig["text"], trig.get("is_mandatory", False),
                     trig.get("soulstone_cost", 0), trig.get("applies_to")))
            
            # Update description if better one came back
            if card.get("description"):
                c.execute("UPDATE upgrades SET description=?, parse_status='auto' WHERE id=?",
                          (card["description"], uid))
            else:
                c.execute("UPDATE upgrades SET parse_status='auto' WHERE id=?", (uid,))
            
            conn.commit()
            print(f"  LOADED {len(triggers)} triggers to DB")
            
        except Exception as e:
            print(f"  ERROR: {e}")
        
        if i < len(flagged) - 1:
            time.sleep(1.5)
    
    # Summary
    c.execute("SELECT COUNT(*) FROM upgrade_granted_triggers")
    total = c.fetchone()[0]
    print(f"\nTotal upgrade_granted_triggers in DB: {total}")
    
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
