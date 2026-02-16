import sqlite3

conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

fixes = [
    (1, "Som'er Teeth Jones (Loot Monger)", "Skeeter"),
    (684, "Lord Cooper (Manhunter)", "Empyrean Eagle"),
    (774, "Lucas McCabe (Tomb Delver)", "Cryptologist"),
    (697, "Tiri (The Architect)", "Unseelie Engine"),
    (304, "Harold Tull (Artillerist)", "Walking Cannon"),
    (305, "Harold Tull (Dead Silent)", "Smokestack"),
    (325, "Lucius Mattheson (Dishonorable)", "Jane Doe"),
    (375, "Scales of Justice", "Asset 17"),
    (708, "Nexus (One of Many)", "-"),
    (439, "The Dreamer (Fast Asleep)", "Lord Chompy Bits"),
    (160, "Viktoria Chambers (Ashes and Blood)", "Student of Conflict"),
    (465, "Kastore (Fervent)", "Urnbearer"),
    (589, "Kirai Ankoku (Envoy of the Court)", "Ikiryo"),
    (533, "Seamus (The Last Breath)", "Copycat Killer"),
    (611, "Jakob Lynch (Dark Bet)", "Hungering Darkness"),
]

for mid, label, totem in fixes:
    c.execute("UPDATE models SET totem=? WHERE id=?", (totem, mid))
    print(f"  {label} -> totem: {totem}")

conn.commit()

c.execute("""SELECT COUNT(*) FROM models 
             WHERE station='Master' AND (totem IS NULL OR totem='')""")
print(f"\nMasters still missing totem: {c.fetchone()[0]}")
conn.close()
