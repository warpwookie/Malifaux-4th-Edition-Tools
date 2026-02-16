import sqlite3
c = sqlite3.connect("db/m4e.db")
for term in ["Ophelia", "Ulix", "Flying Piglet"]:
    rows = c.execute(
        "SELECT id, name, title, faction FROM models WHERE name LIKE ?",
        (f"%{term}%",)
    ).fetchall()
    if rows:
        for r in rows:
            print(f"  id={r[0]}  name='{r[1]}'  title='{r[2]}'  faction={r[3]}")
    else:
        print(f"  NOT FOUND: {term}")
c.close()
