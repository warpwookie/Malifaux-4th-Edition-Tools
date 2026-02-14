import sqlite3
conn = sqlite3.connect('db/m4e.db')
c = conn.cursor()
c.execute("SELECT name, title, faction FROM models WHERE faction != 'Bayou' ORDER BY faction, name")
rows = c.fetchall()
print(f"Models NOT tagged as Bayou: {len(rows)}")
for name, title, faction in rows:
    print(f"  [{faction}] {name} ({title})")
conn.close()
