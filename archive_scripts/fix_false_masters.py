"""
fix_false_masters.py — Revert models incorrectly tagged as Master.
Rule: Real Masters always have cost='-'. Any Master with numeric cost is wrong.
"""
import sqlite3

conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

# Find false Masters
c.execute("""SELECT id, name, title, cost, faction FROM models 
             WHERE station='Master' AND cost != '-' AND cost IS NOT NULL
             ORDER BY id""")
false_masters = c.fetchall()

print(f"False Masters (station=Master but numeric cost): {len(false_masters)}\n")
for mid, name, title, cost, faction in false_masters:
    print(f"  id={mid} {name} ({title}) cost={cost} [{faction}] -> NULL")

# Revert to NULL
c.execute("""UPDATE models SET station=NULL 
             WHERE station='Master' AND cost != '-' AND cost IS NOT NULL""")
print(f"\nReverted {c.rowcount} false Masters to NULL")

# Station distribution after fix
c.execute("""SELECT station, COUNT(*) FROM models 
             GROUP BY station ORDER BY COUNT(*) DESC""")
print("\nStation distribution:")
for station, n in c.fetchall():
    print(f"  {station or 'NULL (no station)'}: {n}")

# Verify: all remaining Masters have cost='-'
c.execute("SELECT COUNT(*) FROM models WHERE station='Master' AND cost != '-'")
bad = c.fetchone()[0]
print(f"\nMasters with non-dash cost: {bad}")

conn.commit()
conn.close()
