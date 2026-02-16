"""
diagnose_warnings.py — Detailed breakdown of all audit warnings.
Helps decide what can be inferred vs what needs re-extraction.
"""
import sqlite3
from collections import Counter

conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

print("=" * 70)
print("WARNING DIAGNOSTICS")
print("=" * 70)

# ============================================================
# 1. NULL STATIONS (338)
# ============================================================
print("\n[1] NULL STATION MODELS")
c.execute("SELECT COUNT(*) FROM models WHERE station IS NULL")
null_station = c.fetchone()[0]
print(f"  Total: {null_station}")

# Can we infer from characteristics?
c.execute("""SELECT m.id, m.name, m.title, m.cost, m.faction,
             GROUP_CONCAT(mc.characteristic, ', ') as chars
             FROM models m
             LEFT JOIN model_characteristics mc ON m.id = mc.model_id
             WHERE m.station IS NULL
             GROUP BY m.id
             LIMIT 20""")
print(f"\n  Sample NULL station models:")
for r in c.fetchall():
    print(f"    id={r[0]} {r[1]} ({r[2]}), cost={r[3]}, faction={r[4]}")
    print(f"      characteristics: {r[5]}")

# Check if station keywords appear in characteristics
c.execute("""SELECT mc.characteristic, COUNT(*) 
             FROM models m JOIN model_characteristics mc ON m.id=mc.model_id
             WHERE m.station IS NULL
             AND mc.characteristic IN ('Master', 'Henchman', 'Enforcer', 'Minion', 'Totem', 'Peon')
             GROUP BY mc.characteristic""")
inferrable = c.fetchall()
print(f"\n  Station values found in characteristics of NULL-station models:")
for r in inferrable:
    print(f"    {r[0]}: {r[1]} models")

# How many can't be inferred?
c.execute("""SELECT COUNT(*) FROM models m
             WHERE m.station IS NULL
             AND NOT EXISTS (
                 SELECT 1 FROM model_characteristics mc 
                 WHERE mc.model_id = m.id 
                 AND mc.characteristic IN ('Master','Henchman','Enforcer','Minion','Totem','Peon')
             )""")
cant_infer = c.fetchone()[0]
print(f"  Cannot infer from characteristics: {cant_infer}")

# ============================================================
# 2. NO KEYWORDS (123)
# ============================================================
print("\n" + "=" * 70)
print("[2] MODELS WITH NO KEYWORDS")
c.execute("""SELECT COUNT(*) FROM models m
             WHERE NOT EXISTS (SELECT 1 FROM model_keywords WHERE model_id=m.id)""")
no_kw = c.fetchone()[0]
print(f"  Total: {no_kw}")

# By faction
c.execute("""SELECT m.faction, COUNT(*) FROM models m
             WHERE NOT EXISTS (SELECT 1 FROM model_keywords WHERE model_id=m.id)
             GROUP BY m.faction ORDER BY COUNT(*) DESC""")
print(f"\n  By faction:")
for r in c.fetchall():
    print(f"    {r[0]}: {r[1]}")

# Sample
c.execute("""SELECT m.id, m.name, m.title, m.faction, m.station FROM models m
             WHERE NOT EXISTS (SELECT 1 FROM model_keywords WHERE model_id=m.id)
             LIMIT 15""")
print(f"\n  Sample:")
for r in c.fetchall():
    print(f"    id={r[0]} {r[1]} ({r[2]}) [{r[3]}] station={r[4]}")

# ============================================================
# 3. TRIGGERS WITH NO SUIT (77)
# ============================================================
print("\n" + "=" * 70)
print("[3] TRIGGERS WITH NO SUIT")
c.execute("""SELECT t.id, t.name, t.timing, a.name, m.name, m.title, m.faction
             FROM triggers t
             JOIN actions a ON t.action_id=a.id
             JOIN models m ON a.model_id=m.id
             WHERE t.suit IS NULL OR t.suit = ''
             ORDER BY m.faction, m.name""")
no_suit = c.fetchall()
print(f"  Total: {len(no_suit)}")

# By faction
factions = Counter(r[6] for r in no_suit)
print(f"\n  By faction:")
for f, n in factions.most_common():
    print(f"    {f}: {n}")

# By model (are they clustered?)
models = Counter(f"{r[4]} ({r[5]})" for r in no_suit)
print(f"\n  By model (top 10):")
for m, n in models.most_common(10):
    print(f"    {m}: {n} triggers")

# ============================================================
# 4. MASTERS WITH NO CREW_CARD_NAME (30)
# ============================================================
print("\n" + "=" * 70)
print("[4] MASTERS WITH NO CREW_CARD_NAME")
c.execute("""SELECT m.id, m.name, m.title, m.faction FROM models m
             WHERE m.station='Master' AND (m.crew_card_name IS NULL OR m.crew_card_name='')
             ORDER BY m.faction, m.name""")
no_crew = c.fetchall()
print(f"  Total: {len(no_crew)}")

# Check if crew cards exist for these masters
for r in no_crew:
    mid, name, title, faction = r
    c.execute("""SELECT id, name FROM crew_cards 
                 WHERE associated_master=? OR name LIKE ?""", 
              (name, f"%{name}%"))
    matches = c.fetchall()
    match_str = ", ".join(f"'{m[1]}'" for m in matches) if matches else "NONE"
    print(f"  id={mid} {name} ({title}) [{faction}] -> crew cards: {match_str}")

# ============================================================
# 5. MASTERS WITH NO TOTEM (33)
# ============================================================
print("\n" + "=" * 70)
print("[5] MASTERS WITH NO TOTEM")
c.execute("""SELECT m.id, m.name, m.title, m.faction FROM models m
             WHERE m.station='Master' AND (m.totem IS NULL OR m.totem='')
             ORDER BY m.faction, m.name""")
no_totem = c.fetchall()
print(f"  Total: {len(no_totem)}")
for r in no_totem:
    print(f"  id={r[0]} {r[1]} ({r[2]}) [{r[3]}]")

# ============================================================
# 6. ATTACK ACTIONS WITH NO DAMAGE (211) — sample
# ============================================================
print("\n" + "=" * 70)
print("[6] ATTACK ACTIONS WITH NO DAMAGE (sample)")
c.execute("""SELECT a.name, m.name, m.title, a.action_type, a.range, a.skill_value, a.resist, a.effects
             FROM actions a JOIN models m ON a.model_id=m.id
             WHERE a.category='attack_actions' AND (a.damage IS NULL OR a.damage='')
             LIMIT 30""")
no_dmg = c.fetchall()
print(f"  Showing first 30 of 211:")
for r in no_dmg:
    effects_preview = (r[7] or "")[:60]
    print(f"    '{r[0]}' on {r[1]} ({r[2]}): type={r[3]} rg={r[4]} sk={r[5]} vs {r[6]}")
    print(f"      effects: {effects_preview}...")

# ============================================================
# 7. SPOT-CHECK: sp=0 models, sp=9, sz=0
# ============================================================
print("\n" + "=" * 70)
print("[7] STATISTICAL OUTLIERS TO SPOT-CHECK")
c.execute("""SELECT id, name, title, faction, sz, sp, health, source_pdf 
             FROM models WHERE sz=0 OR sp=0 OR sp>8""")
outliers = c.fetchall()
for r in outliers:
    print(f"  id={r[0]} {r[1]} ({r[2]}) [{r[3]}]: sz={r[4]} sp={r[5]} hp={r[6]}")

# ============================================================
# 8. ON TOUR CREW CARD
# ============================================================
print("\n" + "=" * 70)
print("[8] ON TOUR CREW CARD")
c.execute("""SELECT cc.id, cc.name, cc.associated_master, cc.associated_title, cc.faction
             FROM crew_cards cc
             WHERE NOT EXISTS (
                 SELECT 1 FROM models m 
                 WHERE m.name = cc.associated_master AND m.station = 'Master'
             )""")
for r in c.fetchall():
    print(f"  id={r[0]} '{r[1]}' master='{r[2]}' title='{r[3]}' faction={r[4]}")
    # Check what Wrath's station is
    c.execute("SELECT id, name, station FROM models WHERE name=?", (r[2],))
    for m in c.fetchall():
        print(f"    Model: id={m[0]} {m[1]} station={m[2]}")

conn.close()
print("\n" + "=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
