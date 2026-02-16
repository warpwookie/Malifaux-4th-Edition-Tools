import sqlite3
c = sqlite3.connect("db/m4e.db").cursor()
c.execute("""SELECT m.id, m.name, m.faction, m.source_pdf, 
             GROUP_CONCAT(mk.keyword) as keywords
             FROM models m 
             LEFT JOIN model_keywords mk ON m.id = mk.model_id
             WHERE m.name IN ('Jebediah Jones', 'Delirium')
             GROUP BY m.id""")
for r in c.fetchall():
    print(f"{r[1]}: faction={r[2]}, keywords={r[4]}, pdf={r[3]}")
