"""
fix_parker_cleanup.py — Clean up after Bandit keyword re-run.
1. Delete duplicate models (higher IDs) from re-extraction
2. Set Parker Barrows station to Master
3. Link Parker crew cards
"""
import sqlite3

conn = sqlite3.connect("db/m4e.db")
conn.execute("PRAGMA foreign_keys=ON")
c = conn.cursor()

# 1. Find and remove duplicate models from re-run (higher IDs)
dupes = [
    (90, 792, "Ashen Echo"),
    (92, 793, "Convict Gunslinger"),
    (96, 794, "Mad Dog Brackett"),
    (99, 795, "Pearl Musgrove"),
    (101, 796, "Sue"),
]

print("Removing duplicate models from Bandit re-run:")
for old_id, new_id, name in dupes:
    # Delete triggers, actions, abilities, characteristics, keywords, factions for new ID
    c.execute("DELETE FROM triggers WHERE action_id IN (SELECT id FROM actions WHERE model_id=?)", (new_id,))
    c.execute("DELETE FROM actions WHERE model_id=?", (new_id,))
    c.execute("DELETE FROM abilities WHERE model_id=?", (new_id,))
    c.execute("DELETE FROM model_characteristics WHERE model_id=?", (new_id,))
    c.execute("DELETE FROM model_keywords WHERE model_id=?", (new_id,))
    try:
        c.execute("DELETE FROM model_factions WHERE model_id=?", (new_id,))
    except:
        pass
    c.execute("DELETE FROM models WHERE id=?", (new_id,))
    print(f"  Deleted id={new_id} {name} (keeping id={old_id})")

# 2. Check Parker Barrows
c.execute("SELECT id, name, title, station, cost FROM models WHERE name LIKE '%Parker%'")
parkers = c.fetchall()
print(f"\nParker Barrows models:")
for r in parkers:
    print(f"  id={r[0]} {r[1]} ({r[2]}) station={r[3]} cost={r[4]}")

# Set station to Master if cost is '-'
for mid, name, title, station, cost in parkers:
    if cost == '-' and station != 'Master':
        c.execute("UPDATE models SET station='Master' WHERE id=?", (mid,))
        print(f"  -> Set id={mid} {name} ({title}) to Master")

# 3. Check crew card linkage
c.execute("""SELECT cc.name, cc.associated_master, cc.associated_title
             FROM crew_cards cc WHERE cc.associated_master LIKE '%Parker%'""")
crew = c.fetchall()
print(f"\nParker crew cards:")
for r in crew:
    print(f"  '{r[0]}' -> {r[1]} ({r[2]})")

# Verify the fix
c.execute("""SELECT cc.name FROM crew_cards cc
             WHERE NOT EXISTS (
                 SELECT 1 FROM models m 
                 WHERE m.name = cc.associated_master 
                 AND m.station IN ('Master', 'Henchman')
             )""")
orphans = c.fetchall()
print(f"\nOrphan crew cards remaining: {len(orphans)}")
for r in orphans:
    print(f"  {r[0]}")

conn.commit()

# Final count
c.execute("SELECT COUNT(*) FROM models")
print(f"\nTotal models: {c.fetchone()[0]}")
conn.close()
