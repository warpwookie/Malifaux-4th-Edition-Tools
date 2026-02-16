import sqlite3

conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

fixes = [
    # Misclassified as Master
    (53, "Hans", "Enforcer"),
    (103, "Lelu", "Enforcer"),
    (155, "Minako Rei", "Enforcer"),
    # "Marshal" is a keyword, not a station — these are Enforcers
    (96, "Scales of Justice", "Enforcer"),
    (97, "The Jury", "Enforcer"),
    (98, "The Lone Marshal", "Enforcer"),
    (99, "Director Rodriguez", "Enforcer"),
]

for mid, name, station in fixes:
    c.execute("UPDATE models SET station=? WHERE id=?", (station, mid))
    print(f"  id={mid} {name} -> {station}")

conn.commit()
c.execute("SELECT COUNT(*) FROM models WHERE station IS NULL")
print(f"\nRemaining null stations: {c.fetchone()[0]}")
conn.close()
