"""Fix Ophelia casing dupe and normalize remaining names."""
import sqlite3, sys

DRY_RUN = "--apply" not in sys.argv
conn = sqlite3.connect("db/m4e.db")
conn.execute("PRAGMA foreign_keys=ON")
c = conn.cursor()

# 1. Merge Ophelia Overloaded: keep id=36, delete id=44
keep, delete = 36, 44
print(f"Merging Ophelia Overloaded: keep id={keep}, delete id={delete}")

if not DRY_RUN:
    # Transfer any unique factions
    for (fac,) in c.execute("SELECT faction FROM model_factions WHERE model_id=?", (delete,)):
        c.execute("INSERT OR IGNORE INTO model_factions (model_id, faction) VALUES (?,?)", (keep, fac))
    
    # Delete duplicate
    c.execute("DELETE FROM model_factions WHERE model_id=?", (delete,))
    c.execute("DELETE FROM model_keywords WHERE model_id=?", (delete,))
    c.execute("DELETE FROM model_characteristics WHERE model_id=?", (delete,))
    c.execute("DELETE FROM abilities WHERE model_id=?", (delete,))
    for (aid,) in c.execute("SELECT id FROM actions WHERE model_id=?", (delete,)).fetchall():
        c.execute("DELETE FROM triggers WHERE action_id=?", (aid,))
    c.execute("DELETE FROM actions WHERE model_id=?", (delete,))
    c.execute("DELETE FROM models WHERE id=?", (delete,))

# 2. Normalize names on remaining Ophelias
for model_id, new_name, new_title in [(36, "Ophelia LaCroix", "Overloaded"), (45, "Ophelia LaCroix", "Red Cage Raider")]:
    print(f"Normalizing id={model_id} -> '{new_name}' ({new_title})")
    if not DRY_RUN:
        c.execute("UPDATE models SET name=?, title=? WHERE id=?", (new_name, new_title, model_id))

if not DRY_RUN:
    conn.commit()
    print("\nDone.")
else:
    print("\nDry run — use --apply to execute.")

conn.close()
