"""
load_patched_stats.py — Load the 9 stat cards that were patched by fix_stat_failures.py
but failed to load due to wrong key name.

Usage:
  python load_patched_stats.py
"""
import os, json, sys, sqlite3

DB_PATH = os.path.join("db", "m4e.db")

# The 9 cards that need loading (already patched, renamed from _FAILED)
CARDS = [
    ("Arcanists", "M4E_Stat_Performer_Mechanical_Dove_A.json"),
    ("Explorer's Society", "M4E_Stat_Apex_Empyrean_Eagle_A.json"),
    ("Explorer's Society", "M4E_Stat_Apex_Runaway_A.json"),
    ("Explorer's Society", "M4E_Stat_Wastrel_Cryptologist_A.json"),
    ("Guild", "M4E_Stat_Cavalier_Walking_Cannon_A.json"),
    ("Neverborn", "M4E_Stat_Returned_Marathine.json"),
    ("Neverborn", "M4E_Stat_Returned_Urnbearer_A.json"),
    ("Outcasts", "M4E_Stat_Amalgam_Hollow_Waif_A.json"),
    ("Ten Thunders", "M4E_Stat_Qi-and-Gong_Kunoichi_A.json"),
]

sys.path.insert(0, "scripts")
from db_loader import load_stat_card

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys=ON")

loaded = 0
errors = 0

for faction, filename in CARDS:
    fpath = os.path.join("pipeline_work", faction, filename)
    
    # Try to find the file if exact name doesn't match
    if not os.path.exists(fpath):
        # Search for partial match
        folder = os.path.join("pipeline_work", faction)
        base = filename.replace(".json", "").replace("_A", "")
        candidates = [f for f in os.listdir(folder) 
                      if f.endswith(".json") and not f.endswith("_merged.json")
                      and "FAILED" not in f and "Crew" not in f
                      and base.split("_")[-1].lower() in f.lower()]
        if candidates:
            fpath = os.path.join(folder, candidates[0])
            print(f"  Note: Using {candidates[0]} for {filename}")
        else:
            print(f"  SKIP: Could not find {fpath}")
            errors += 1
            continue

    d = json.load(open(fpath, encoding="utf-8"))
    card = d.get("card", d.get("merged", d.get("front", {})))
    
    # Ensure factions list
    factions = card.get("factions", [card.get("faction", faction)])
    if faction not in factions:
        factions.append(faction)
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
        print(f"  Loaded [{faction}] {card.get('name','?')} ({result['status']}, id={model_id})")
        loaded += 1
    except Exception as e:
        print(f"  ERROR [{faction}] {card.get('name','?')}: {e}")
        conn.rollback()
        errors += 1

conn.close()
print(f"\nDone: {loaded} loaded, {errors} errors")
