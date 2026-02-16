import sqlite3

conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

# All confirmed stat outliers
verified_ids = [
    (5, "Gupps", "sz=0"),
    (62, "Voodoo Doll", "sz=0"),
    (360, "Camerabot", "sz=0, sp=0"),
    (103, "Ashen Core", "sp=0"),
    (509, "Last Bite", "sp=0"),
    (625, "Sunless Self", "sp=9"),
    (238, "Clockwork Trap", "wp=0, sp=0"),  # previously verified but confirming
    (784, "Marathine", "health=0"),          # previously verified but confirming
]

for mid, name, reason in verified_ids:
    c.execute("UPDATE models SET parse_status='verified' WHERE id=?", (mid,))
    print(f"  id={mid} {name} ({reason}) -> verified")

conn.commit()
print(f"\nMarked {len(verified_ids)} models as verified")
conn.close()
