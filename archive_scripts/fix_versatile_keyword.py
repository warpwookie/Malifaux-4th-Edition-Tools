import sqlite3

conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

# Find all models with "Versatile" as a keyword
c.execute("""SELECT mk.model_id, m.name, m.title, m.faction 
             FROM model_keywords mk
             JOIN models m ON mk.model_id = m.id
             WHERE mk.keyword = 'Versatile'
             ORDER BY m.faction, m.name""")
rows = c.fetchall()
print(f"Models with 'Versatile' as keyword: {len(rows)}\n")

# Check which of these ALSO have it as a characteristic (should be all)
for mid, name, title, faction in rows:
    c.execute("SELECT characteristic FROM model_characteristics WHERE model_id=? AND characteristic='Versatile'", (mid,))
    has_char = c.fetchone() is not None
    
    # Check how many other keywords this model has
    c.execute("SELECT keyword FROM model_keywords WHERE model_id=? AND keyword != 'Versatile'", (mid,))
    other_kws = [r[0] for r in c.fetchall()]
    
    status = "also in characteristics" if has_char else "NOT in characteristics!"
    kw_status = f"other keywords: {other_kws}" if other_kws else "NO other keywords"
    print(f"  [{faction}] {name} ({title}) — {status}, {kw_status}")

# Remove Versatile from keywords
c.execute("DELETE FROM model_keywords WHERE keyword = 'Versatile'")
print(f"\nRemoved {c.rowcount} 'Versatile' entries from model_keywords")

# Ensure all removed models have Versatile in characteristics
for mid, name, title, faction in rows:
    c.execute("SELECT 1 FROM model_characteristics WHERE model_id=? AND characteristic='Versatile'", (mid,))
    if not c.fetchone():
        c.execute("INSERT INTO model_characteristics (model_id, characteristic) VALUES (?, 'Versatile')", (mid,))
        print(f"  Added Versatile to characteristics for {name} ({title})")

# Check how many models now have no keywords at all
c.execute("""SELECT m.id, m.name, m.title, m.faction FROM models m
             WHERE m.id NOT IN (SELECT model_id FROM model_keywords)
             ORDER BY m.faction, m.name""")
no_kw = c.fetchall()
print(f"\nModels with no keywords after cleanup: {len(no_kw)}")
for mid, name, title, faction in no_kw:
    print(f"  id={mid} {name} ({title}) [{faction}]")

conn.commit()
conn.close()
