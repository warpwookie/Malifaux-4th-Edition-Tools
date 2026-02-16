import sqlite3

conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

c.execute("""SELECT m.id, m.name, m.title, m.faction, m.station, m.source_pdf
             FROM models m
             WHERE m.id NOT IN (SELECT model_id FROM model_keywords)
             ORDER BY m.faction, m.name""")

rows = c.fetchall()
print(f"Models with no keywords: {len(rows)}\n")
for mid, name, title, faction, station, src in rows:
    print(f"  id={mid} {name} ({title}) [{faction}] station={station}")
    print(f"    source_pdf: {src}")

    # Check characteristics
    c.execute("SELECT characteristic FROM model_characteristics WHERE model_id=?", (mid,))
    chars = [r[0] for r in c.fetchall()]
    print(f"    characteristics: {chars}")
    print()

conn.close()
