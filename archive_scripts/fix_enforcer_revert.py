"""
fix_enforcer_revert.py — Remove hallucinated "Enforcer" station.

M4E has no Enforcer station. Valid stations: Master, Henchman, Minion, Totem, Peon.
Models previously tagged Enforcer revert to NULL (station unknown/not applicable).
"""
import sqlite3

DB_PATH = "db/m4e.db"
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Count current Enforcers
c.execute("SELECT COUNT(*) FROM models WHERE station='Enforcer'")
count = c.fetchone()[0]
print(f"Models with station='Enforcer': {count}")

# Show breakdown by faction
c.execute("""SELECT faction, COUNT(*) FROM models 
             WHERE station='Enforcer' GROUP BY faction ORDER BY faction""")
print("\nBy faction:")
for faction, n in c.fetchall():
    print(f"  {faction}: {n}")

# Revert all Enforcers to NULL
c.execute("UPDATE models SET station=NULL WHERE station='Enforcer'")
print(f"\nReverted {count} models from 'Enforcer' to NULL")

# Verify no Enforcers remain
c.execute("SELECT COUNT(*) FROM models WHERE station='Enforcer'")
remaining = c.fetchone()[0]
print(f"Remaining Enforcers: {remaining}")

# Show station distribution
c.execute("""SELECT station, COUNT(*) FROM models 
             GROUP BY station ORDER BY COUNT(*) DESC""")
print("\nStation distribution:")
for station, n in c.fetchall():
    print(f"  {station or 'NULL'}: {n}")

conn.commit()
conn.close()
