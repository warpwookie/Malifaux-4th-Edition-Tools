import sqlite3
c = sqlite3.connect("db/m4e.db")
for term in ["Tull", "Kastore", "Alyce", "Heavy Salvo", "Boosted", "Offering"]:
    rows = c.execute(
        "SELECT id, name, associated_master, associated_title FROM crew_cards "
        "WHERE name LIKE ? OR associated_master LIKE ?",
        (f"%{term}%", f"%{term}%")
    ).fetchall()
    if rows:
        for r in rows:
            print(f"  id={r[0]}  name='{r[1]}'  master='{r[2]}'  title='{r[3]}'")
    else:
        print(f"  No crew cards matching '{term}'")
    print()
c.close()
