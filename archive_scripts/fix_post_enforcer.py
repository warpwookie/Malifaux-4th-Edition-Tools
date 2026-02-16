"""
fix_post_enforcer.py — After Enforcer revert:
1. Check NULL-station models for Henchman characteristic → set station
2. Update reference_data.json to remove Enforcer
"""
import sqlite3
import json

DB_PATH = "db/m4e.db"
REF_PATH = "reference_data.json"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Step 1: Find NULL-station models with Henchman in characteristics
c.execute("""SELECT m.id, m.name, m.title, m.faction
             FROM models m
             JOIN model_characteristics mc ON m.id = mc.model_id
             WHERE m.station IS NULL AND mc.characteristic = 'Henchman'
             ORDER BY m.faction, m.name""")
henchmen = c.fetchall()

print(f"NULL-station models with Henchman characteristic: {len(henchmen)}")
for mid, name, title, faction in henchmen:
    print(f"  id={mid} {name} ({title}) [{faction}]")

# Apply
for mid, name, title, faction in henchmen:
    c.execute("UPDATE models SET station='Henchman' WHERE id=?", (mid,))

print(f"\nSet {len(henchmen)} models to Henchman")

# Final station distribution
c.execute("""SELECT station, COUNT(*) FROM models 
             GROUP BY station ORDER BY COUNT(*) DESC""")
print("\nStation distribution:")
for station, n in c.fetchall():
    print(f"  {station or 'NULL (no station)'}: {n}")

conn.commit()
conn.close()

# Step 2: Update reference_data.json
with open(REF_PATH, "r") as f:
    ref = json.load(f)

if "Enforcer" in ref.get("stations", []):
    ref["stations"].remove("Enforcer")
    print(f"\nRemoved 'Enforcer' from reference_data.json stations")
    print(f"Valid stations: {ref['stations']}")
    with open(REF_PATH, "w") as f:
        json.dump(ref, f, indent=2)
else:
    print(f"\n'Enforcer' not in reference_data.json (already clean)")
