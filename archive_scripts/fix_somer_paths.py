import sqlite3
from pathlib import Path

conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

# Direct paths from the search output
somer_loot = None
somer_boss = None

for p in Path("source_pdfs").rglob("*.pdf"):
    if "Somer" in p.name or "Som" in p.name:
        if "Loot_Monger" in p.name:
            somer_loot = str(p)
        elif "Bayou_Boss" in p.name and "Stat" in p.name:
            somer_boss = str(p)

if somer_loot:
    c.execute("UPDATE models SET source_pdf=? WHERE id=1", (somer_loot,))
    print(f"  id=1 Som'er (Loot Monger) -> {Path(somer_loot).name}")
else:
    print("  id=1 Som'er (Loot Monger) -> NOT FOUND")

if somer_boss:
    c.execute("UPDATE models SET source_pdf=? WHERE id=16", (somer_boss,))
    print(f"  id=16 Som'er (Bayou Boss) -> {Path(somer_boss).name}")
else:
    print("  id=16 Som'er (Bayou Boss) -> NOT FOUND")

conn.commit()
c.execute("SELECT COUNT(*) FROM models WHERE source_pdf IS NULL OR source_pdf=''")
print(f"\nRemaining without source_pdf: {c.fetchone()[0]}")
conn.close()
