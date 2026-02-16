import sqlite3
from pathlib import Path

conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

# 1. How many models have multiple factions in model_factions?
c.execute("""SELECT model_id, COUNT(*) as fc FROM model_factions 
             GROUP BY model_id HAVING fc > 1""")
multi = c.fetchall()
print(f"Models with multiple faction entries: {len(multi)}")

# 2. Show some examples
print("\nExamples of multi-faction models:")
for mid, fc in multi[:10]:
    c.execute("SELECT name, title, faction FROM models WHERE id=?", (mid,))
    name, title, primary = c.fetchone()
    c.execute("SELECT faction FROM model_factions WHERE model_id=?", (mid,))
    factions = [r[0] for r in c.fetchall()]
    print(f"  id={mid} {name} ({title}) primary={primary} -> model_factions={factions}")

# 3. Are there models where model_factions doesn't include the primary faction?
c.execute("""SELECT m.id, m.name, m.faction FROM models m
             WHERE m.faction NOT IN (
                 SELECT mf.faction FROM model_factions mf WHERE mf.model_id = m.id
             )""")
mismatched = c.fetchall()
print(f"\nModels where primary faction not in model_factions: {len(mismatched)}")

# 4. Count source PDFs per faction folder
print("\nSource PDF stat card counts by faction folder:")
source_dir = Path("source_pdfs")
if source_dir.exists():
    for faction_dir in sorted(source_dir.iterdir()):
        if not faction_dir.is_dir():
            continue
        stat_count = 0
        unique_models = set()
        for kw_dir in faction_dir.iterdir():
            if not kw_dir.is_dir():
                continue
            for pdf in kw_dir.glob("M4E_Stat_*.pdf"):
                stat_count += 1
                # Strip variant suffix (_A, _B, _C etc)
                name = pdf.stem
                parts = name.rsplit("_", 1)
                if len(parts) == 2 and len(parts[1]) == 1 and parts[1].isalpha():
                    name = parts[0]
                unique_models.add(name)
        print(f"  {faction_dir.name}: {stat_count} PDFs, ~{len(unique_models)} unique models")

# 5. DB primary faction counts for comparison
print("\nDB primary faction counts:")
c.execute("SELECT faction, COUNT(*) FROM models GROUP BY faction ORDER BY faction")
for faction, count in c.fetchall():
    print(f"  {faction}: {count}")

conn.close()
