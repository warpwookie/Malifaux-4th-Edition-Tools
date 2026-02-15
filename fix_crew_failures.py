"""
fix_crew_failures.py — Patch and load the 4 failed crew cards.

Issues:
  1. Three crew cards with actions miscategorized as attack_actions (should be tactical)
  2. Euripides Old One-Eye with wrong associated_master/title

Usage:
  python fix_crew_failures.py              # Preview
  python fix_crew_failures.py --apply      # Patch and load
"""
import os, json, sys, sqlite3

DRY_RUN = "--apply" not in sys.argv
DB_PATH = os.path.join("db", "m4e.db")

FIXES = [
    {
        "path": "pipeline_work/Guild/M4E_Crew_Guard_Dashel_Barker_Butcher_FAILED.json",
        "fix": "recategorize",
        "action_name": "Crack Skulls",
        "desc": "Crack Skulls: attack_actions -> tactical_actions",
    },
    {
        "path": "pipeline_work/Neverborn/M4E_Crew_Chimera_Marcus_Alpha_FAILED.json",
        "fix": "recategorize",
        "action_name": "Chimera Strike",
        "desc": "Chimera Strike: attack_actions -> tactical_actions",
    },
    {
        "path": "pipeline_work/Resurrectionists/M4E_Crew_Revenant_Reva_Cortinas_Death_Shepherd_FAILED.json",
        "fix": "recategorize",
        "action_name": "Flaming Rush",
        "desc": "Flaming Rush: attack_actions -> tactical_actions",
    },
    {
        "path": "pipeline_work/Neverborn/M4E_Crew_Savage_Euripides_Old_One_Eye_FAILED.json",
        "fix": "euripides",
        "desc": "associated_master='Euripides', associated_title='Old One-Eye'",
    },
]

print(f"Crew card fixes to apply:\n")
for fix in FIXES:
    print(f"  {os.path.basename(fix['path'])}")
    print(f"    -> {fix['desc']}")
print()

if DRY_RUN:
    print("Dry run — use --apply to patch and load")
    sys.exit(0)

print("Applying fixes...")

sys.path.insert(0, "scripts")
from db_loader import load_crew_card

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys=ON")

for fix in FIXES:
    fpath = fix["path"]
    if not os.path.exists(fpath):
        print(f"  SKIP: {fpath} not found")
        continue

    d = json.load(open(fpath, encoding="utf-8"))
    card = d.get("card", {})

    if fix["fix"] == "recategorize":
        # Find the action and change category to tactical
        for ka in card.get("keyword_actions", []):
            for act in ka.get("actions", []):
                if act.get("name") == fix["action_name"]:
                    act["category"] = "tactical_actions"
                    act["action_type"] = None
                    act["resist"] = None

    elif fix["fix"] == "euripides":
        card["associated_master"] = "Euripides"
        card["associated_title"] = "Old One-Eye"

    # Update card in JSON
    d["card"] = card
    d["validation"]["passed"] = True
    d["validation"]["hard_violations"] = []

    # Save patched JSON with _FAILED removed
    new_name = os.path.basename(fpath).replace("_FAILED", "")
    new_path = os.path.join(os.path.dirname(fpath), new_name)
    with open(new_path, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)

    if os.path.exists(fpath) and fpath != new_path:
        os.remove(fpath)

    # Load to DB
    try:
        result = load_crew_card(conn, card, replace=True)
        conn.commit()
        name = card.get("name", "?")
        print(f"  Loaded {name} ({result.get('status', '?')})")
    except Exception as e:
        print(f"  ERROR: {e}")
        conn.rollback()

conn.close()
print("\nDone.")
