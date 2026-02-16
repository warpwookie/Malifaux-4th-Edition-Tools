import sqlite3

conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

c.execute("""SELECT m.id, m.name, m.title, m.faction, 
             GROUP_CONCAT(mk.keyword) as keywords
             FROM models m
             LEFT JOIN model_keywords mk ON m.id = mk.model_id
             WHERE m.station='Master' AND (m.totem IS NULL OR m.totem='')
             GROUP BY m.id
             ORDER BY m.faction, m.name, m.title""")

rows = c.fetchall()
print(f"Masters with no totem: {len(rows)}\n")

current_faction = None
for mid, name, title, faction, keywords in rows:
    if faction != current_faction:
        current_faction = faction
        print(f"\n{faction}:")
    print(f"  {name} ({title}) — keywords: {keywords or 'none'}")

# Also show all totems in the DB for reference
print(f"\n{'='*60}")
print("Known Totems in DB:")
c.execute("""SELECT m.name, m.title, m.faction, 
             GROUP_CONCAT(mk.keyword) as keywords
             FROM models m
             LEFT JOIN model_keywords mk ON m.id = mk.model_id
             WHERE m.station='Totem'
             GROUP BY m.id
             ORDER BY m.faction, m.name""")
for name, title, faction, keywords in c.fetchall():
    print(f"  [{faction}] {name} ({title}) — keywords: {keywords or 'none'}")

conn.close()
