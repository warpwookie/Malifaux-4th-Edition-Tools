import sqlite3

conn = sqlite3.connect("db/m4e.db")
conn.execute("PRAGMA foreign_keys=ON")
c = conn.cursor()

# Check all Ophelias
print("=== Ophelia models ===")
for r in c.execute("""
    SELECT m.id, m.name, m.title, m.faction,
        (SELECT COUNT(*) FROM abilities WHERE model_id=m.id) +
        (SELECT COUNT(*) FROM actions WHERE model_id=m.id) as richness
    FROM models m WHERE UPPER(m.name) LIKE '%OPHELIA%'
    ORDER BY m.title, m.id
""").fetchall():
    print(f"  id={r[0]}  name='{r[1]}'  title='{r[2]}'  faction={r[3]}  richness={r[4]}")

print()

# Check what's there for Ulix
print("=== Ulix models ===")
for r in c.execute("SELECT id, name, title, faction FROM models WHERE name LIKE '%Ulix%'").fetchall():
    print(f"  id={r[0]}  name='{r[1]}'  title='{r[2]}'  faction={r[3]}")

print()

# Check for any Piglet variants
print("=== Piglet models ===")
for r in c.execute("SELECT id, name, title, faction FROM models WHERE name LIKE '%Piglet%' OR name LIKE '%piglet%'").fetchall():
    print(f"  id={r[0]}  name='{r[1]}'  title='{r[2]}'  faction={r[3]}")

conn.close()
