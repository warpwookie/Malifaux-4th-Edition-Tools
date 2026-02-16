"""
fix_audit_round2.py — Fix remaining audit errors.

1. Fix crew cards with wrong associated_master values
2. Add upgrade_granted_triggers table for trigger-granting upgrades
3. Re-extract the 5 empty upgrades into new schema

Usage:
    python fix_audit_round2.py              # Preview
    python fix_audit_round2.py --apply      # Apply
"""
import sqlite3
import sys

DRY_RUN = "--apply" not in sys.argv
DB_PATH = "db/m4e.db"

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys=ON")
c = conn.cursor()

print("=" * 60)
print("Audit Round 2 Fixes")
print("=" * 60)

# ============================================================
# 1. INVESTIGATE BAD CREW CARD MASTER REFS
# ============================================================
print("\n[1/3] Crew card master references...")

# Show the bad ones
c.execute("""SELECT id, name, associated_master, associated_title, faction 
             FROM crew_cards 
             WHERE name IN ('Nekima, Broodmother', 'On Tour')""")
bad_crew = c.fetchall()
for row in bad_crew:
    print(f"  id={row[0]} name='{row[1]}' master='{row[2]}' title='{row[3]}' faction={row[4]}")

# Check what Nekima masters exist
print("\n  Nekima models in DB:")
c.execute("SELECT id, name, title, station FROM models WHERE name LIKE '%Nekima%'")
for r in c.fetchall():
    print(f"    id={r[0]} {r[1]} ({r[2]}) station={r[3]}")

# Check for Wrath
print("\n  Models named 'Wrath' or crew cards for similar:")
c.execute("SELECT id, name, title, station FROM models WHERE name LIKE '%Wrath%'")
for r in c.fetchall():
    print(f"    id={r[0]} {r[1]} ({r[2]}) station={r[3]}")

# Check On Tour crew card context
print("\n  'On Tour' crew card details:")
c.execute("""SELECT cc.id, cc.name, cc.associated_master, cc.associated_title, cc.faction,
             cc.source_pdf FROM crew_cards cc WHERE cc.name = 'On Tour'""")
for r in c.fetchall():
    print(f"    id={r[0]} name='{r[1]}' master='{r[2]}' title='{r[3]}' faction={r[4]}")
    print(f"    source: {r[5]}")

# Look for Colette or other Performers master
print("\n  Possible 'On Tour' masters (Performer/Showgirl keyword):")
c.execute("""SELECT m.id, m.name, m.title, m.station FROM models m
             JOIN model_keywords mk ON m.id = mk.model_id
             WHERE mk.keyword IN ('Performer', 'Showgirl') AND m.station = 'Master'""")
for r in c.fetchall():
    print(f"    id={r[0]} {r[1]} ({r[2]}) station={r[3]}")

# Check Nekima Broodmother source
print("\n  'Nekima, Broodmother' crew card source:")
c.execute("SELECT source_pdf FROM crew_cards WHERE name = 'Nekima, Broodmother'")
for r in c.fetchall():
    print(f"    {r[0]}")

print()

# ============================================================
# 2. ADD upgrade_granted_triggers TABLE
# ============================================================
print("[2/3] Adding upgrade_granted_triggers table...")

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS upgrade_granted_triggers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    upgrade_id      INTEGER NOT NULL,
    name            TEXT NOT NULL,
    suit            TEXT,
    timing          TEXT,
    text            TEXT NOT NULL,
    is_mandatory    BOOLEAN DEFAULT 0,
    soulstone_cost  INTEGER DEFAULT 0,
    applies_to      TEXT,                               -- e.g., "all attack actions", "all actions printed on stat card"
    FOREIGN KEY (upgrade_id) REFERENCES upgrades(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_upgrade_granted_triggers ON upgrade_granted_triggers(upgrade_id);
"""

# Check if table exists
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='upgrade_granted_triggers'")
if c.fetchone():
    print("  Table already exists")
else:
    if not DRY_RUN:
        conn.executescript(CREATE_SQL)
        print("  CREATED upgrade_granted_triggers table")
    else:
        print("  WOULD CREATE upgrade_granted_triggers table")

# ============================================================
# 3. PARSE THE 5 EMPTY UPGRADES' DESCRIPTIONS INTO TRIGGERS
# ============================================================
print("\n[3/3] Parsing trigger-granting upgrades from descriptions...")

c.execute("""SELECT u.id, u.name, u.description FROM upgrades u
             WHERE NOT EXISTS (SELECT 1 FROM upgrade_abilities WHERE upgrade_id=u.id)
             AND NOT EXISTS (SELECT 1 FROM upgrade_actions WHERE upgrade_id=u.id)
             AND u.description IS NOT NULL""")
empty = c.fetchall()

for uid, name, desc in empty:
    print(f"\n  id={uid} {name}:")
    print(f"    Description: {desc[:120]}...")
    print(f"    (Will need re-extraction via API to parse triggers properly)")

if not DRY_RUN:
    print("\n  Table created. Empty upgrades need re-extraction with updated prompt.")
    print("  Run: python run_upgrades.py --keyword <keyword> to re-extract.")

print()
if DRY_RUN:
    print("Dry run — use --apply to make changes.")
else:
    print("Done. Next steps:")
    print("  1. Review crew card master refs above and fix manually if needed")
    print("  2. Re-extract 5 flagged upgrades with updated prompt")

conn.close()
