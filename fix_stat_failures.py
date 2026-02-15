"""
fix_stat_failures.py — Patch and load all failed stat cards.

Two issues:
  1. Minion(N) models where model_limit was set to 1 instead of N
  2. Marathine with health=0 (genuine — no health bar on card)

Usage:
  python fix_stat_failures.py              # Preview fixes
  python fix_stat_failures.py --apply      # Apply fixes and load to DB
"""
import os, json, re, sys, sqlite3

DRY_RUN = "--apply" not in sys.argv
BASE = "pipeline_work"
DB_PATH = os.path.join("db", "m4e.db")

fixes = []

for entry in sorted(os.listdir(BASE)):
    path = os.path.join(BASE, entry)
    if not os.path.isdir(path):
        continue
    for f in sorted(os.listdir(path)):
        if "FAILED" not in f or "Stat" not in f:
            continue

        fpath = os.path.join(path, f)
        d = json.load(open(fpath, encoding="utf-8"))
        v = d.get("validation", {})
        card = d.get("merged", d.get("front", {}))
        name = v.get("card_name", card.get("name", "?"))
        hard = v.get("hard_violations", [])

        fixed = False
        reasons = []

        # Fix 1: Minion(N) / model_limit mismatch
        for h in hard:
            m = re.match(r"Minion\((\d+)\) but model_limit=(\d+)", h)
            if m:
                correct_limit = int(m.group(1))
                old_limit = int(m.group(2))
                card["model_limit"] = correct_limit
                reasons.append(f"model_limit {old_limit} -> {correct_limit}")
                fixed = True

        # Fix 2: Marathine health=0 (genuine edge case)
        for h in hard:
            if "health=0" in h and name.upper() == "MARATHINE":
                reasons.append("health=0 accepted (no health bar on card)")
                fixed = True

        if fixed:
            fixes.append({
                "faction": entry,
                "file": f,
                "path": fpath,
                "name": name,
                "reasons": reasons,
                "card": card,
                "full_data": d,
            })

print(f"Found {len(fixes)} stat cards to fix:\n")
for fix in fixes:
    print(f"  [{fix['faction']}] {fix['name']}")
    for r in fix["reasons"]:
        print(f"    -> {r}")
print()

if DRY_RUN:
    print("Dry run — use --apply to patch files and load to DB")
    sys.exit(0)

# Apply fixes
print("Applying fixes...")

sys.path.insert(0, "scripts")
from db_loader import load_stat_card

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys=ON")

for fix in fixes:
    fpath = fix["path"]
    d = fix["full_data"]
    card = fix["card"]

    # Update merged data in the JSON
    if "merged" in d:
        d["merged"] = card
    elif "front" in d:
        d["front"] = card

    # Clear validation failure
    d["validation"]["passed"] = True
    d["validation"]["hard_violations"] = []

    # Rename file: remove _FAILED
    new_name = fix["file"].replace("_FAILED", "")
    new_path = os.path.join(os.path.dirname(fpath), new_name)

    # Save patched JSON
    with open(new_path, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)

    # Remove old FAILED file
    if os.path.exists(fpath) and fpath != new_path:
        os.remove(fpath)

    # Ensure factions list includes source faction
    source_faction = fix["faction"]
    factions = card.get("factions", [card.get("faction", source_faction)])
    if source_faction not in factions:
        factions.append(source_faction)
    card["factions"] = factions

    try:
        result = load_stat_card(conn, card, replace=True)
        model_id = result["model_id"]

        # Update model_factions junction table
        conn.execute("DELETE FROM model_factions WHERE model_id=?", (model_id,))
        for fac in factions:
            conn.execute("INSERT OR IGNORE INTO model_factions (model_id, faction) VALUES (?,?)",
                         (model_id, fac))

        conn.commit()
        print(f"  Loaded [{fix['faction']}] {fix['name']} ({result['status']}, id={model_id})")
    except Exception as e:
        print(f"  ERROR loading [{fix['faction']}] {fix['name']}: {e}")
        conn.rollback()

conn.close()

print(f"\nDone — {len(fixes)} stat cards patched and loaded.")
print("Re-export faction JSONs to pick up these fixes.")
