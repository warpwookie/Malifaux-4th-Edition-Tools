import sqlite3

conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

# 1. Check Scales of Justice
print("=== Scales of Justice ===")
c.execute("""SELECT id, name, title, station, cost, faction FROM models WHERE id=375""")
r = c.fetchone()
print(f"  id={r[0]} {r[1]} ({r[2]}) station={r[3]} cost={r[4]} faction={r[5]}")

c.execute("""SELECT characteristic FROM model_characteristics WHERE model_id=375""")
chars = [r[0] for r in c.fetchall()]
print(f"  Characteristics: {chars}")

c.execute("""SELECT keyword FROM model_keywords WHERE model_id=375""")
kws = [r[0] for r in c.fetchall()]
print(f"  Keywords: {kws}")

c.execute("""SELECT name FROM abilities WHERE model_id=375""")
abs = [r[0] for r in c.fetchall()]
print(f"  Abilities: {abs}")

# Check other Marshal models for summoning references
print("\n=== Other Marshal keyword models (checking for Scales summoning) ===")
c.execute("""SELECT m.id, m.name, m.title, m.station FROM models m
             JOIN model_keywords mk ON m.id = mk.model_id
             WHERE mk.keyword = 'Marshal'
             ORDER BY m.name""")
for r in c.fetchall():
    print(f"  id={r[0]} {r[1]} ({r[2]}) station={r[3]}")

# Check for any ability/action text mentioning "Scales"
c.execute("""SELECT m.name, a.name, a.text FROM abilities a 
             JOIN models m ON a.model_id = m.id
             WHERE a.text LIKE '%Scales of Justice%'""")
refs = c.fetchall()
if refs:
    print("\nAbilities referencing 'Scales of Justice':")
    for r in refs:
        print(f"  {r[0]} -> {r[1]}: {r[2][:120]}")

c.execute("""SELECT m.name, a.name, a.effects FROM actions a 
             JOIN models m ON a.model_id = m.id
             WHERE a.effects LIKE '%Scales of Justice%'""")
refs = c.fetchall()
if refs:
    print("\nActions referencing 'Scales of Justice':")
    for r in refs:
        print(f"  {r[0]} -> {r[1]}: {r[2][:120]}")

c.execute("""SELECT m.name, t.name, t.text FROM triggers t
             JOIN actions a ON t.action_id = a.id
             JOIN models m ON a.model_id = m.id
             WHERE t.text LIKE '%Scales of Justice%'""")
refs = c.fetchall()
if refs:
    print("\nTriggers referencing 'Scales of Justice':")
    for r in refs:
        print(f"  {r[0]} -> {r[1]}: {r[2][:120]}")

# 2. Fix Som'er Loot Monger crew card
print("\n=== Fixing Som'er Loot Monger ===")
c.execute("UPDATE models SET crew_card_name='Snatch ''N Run' WHERE id=1")
print(f"  Set crew_card_name to 'Snatch 'N Run' for id=1")

# 3. Fix Scales of Justice - remove Master station
c.execute("UPDATE models SET station=NULL WHERE id=375")
print(f"  Set Scales of Justice station to NULL (not a Master)")

# Remove totem and crew_card_name that don't apply
c.execute("UPDATE models SET totem=NULL, crew_card_name=NULL WHERE id=375")
print(f"  Cleared totem and crew_card_name for Scales of Justice")

conn.commit()

# Verify
c.execute("""SELECT COUNT(*) FROM models 
             WHERE station='Master' AND (crew_card_name IS NULL OR crew_card_name='')""")
print(f"\nMasters still missing crew_card_name: {c.fetchone()[0]}")

conn.close()
