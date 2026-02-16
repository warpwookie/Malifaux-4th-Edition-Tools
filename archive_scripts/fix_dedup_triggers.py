"""
fix_dedup_triggers.py — Clean up duplicate granted triggers + verify.
"""
import sqlite3

DB_PATH = "db/m4e.db"
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Check for duplicates
c.execute("""SELECT upgrade_id, name, COUNT(*) as cnt 
             FROM upgrade_granted_triggers 
             GROUP BY upgrade_id, name HAVING cnt > 1""")
dupes = c.fetchall()

if dupes:
    print(f"Found {len(dupes)} duplicate trigger entries, deduping...")
    for uid, name, cnt in dupes:
        # Keep the lowest ID, delete the rest
        c.execute("""DELETE FROM upgrade_granted_triggers 
                     WHERE id NOT IN (
                         SELECT MIN(id) FROM upgrade_granted_triggers 
                         WHERE upgrade_id=? AND name=?
                     ) AND upgrade_id=? AND name=?""", (uid, name, uid, name))
        print(f"  {name} (upgrade_id={uid}): removed {cnt-1} dupes")
    conn.commit()
else:
    print("No duplicate triggers found.")

# Show final state
c.execute("SELECT COUNT(*) FROM upgrade_granted_triggers")
print(f"\nTotal upgrade_granted_triggers: {c.fetchone()[0]}")
c.execute("""SELECT u.name, ugt.name, ugt.suit, ugt.timing, ugt.applies_to
             FROM upgrade_granted_triggers ugt 
             JOIN upgrades u ON ugt.upgrade_id = u.id
             ORDER BY u.name""")
for r in c.fetchall():
    print(f"  {r[0]}: {r[2]} {r[1]} ({r[3]}) — {r[4]}")

conn.close()
