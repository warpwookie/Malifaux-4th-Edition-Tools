"""Find models with duplicate names differing only by case."""
import sqlite3

conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

# Find names that appear with different casings
c.execute("""
    SELECT UPPER(name), title, COUNT(*) as cnt, GROUP_CONCAT(id || ':' || name || ':' || faction, ' | ')
    FROM models
    GROUP BY UPPER(name), title
    HAVING cnt > 1
    ORDER BY UPPER(name)
""")

rows = c.fetchall()
print(f"Found {len(rows)} name groups with potential duplicates:\n")
for upper_name, title, count, details in rows:
    title_str = f" ({title})" if title else ""
    print(f"  {upper_name}{title_str}  [{count} entries]")
    for entry in details.split(" | "):
        parts = entry.split(":")
        print(f"    id={parts[0]}  name='{parts[1]}'  faction={parts[2]}")
    print()

conn.close()
