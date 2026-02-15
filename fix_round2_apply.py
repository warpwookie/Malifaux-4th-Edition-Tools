"""
fix_round2_apply.py — Apply targeted fixes.

1. Fix Nekima crew card master ref
2. Fix On Tour crew card master ref + faction
3. Create upgrade_granted_triggers table

Usage:
    python fix_round2_apply.py
"""
import sqlite3

DB_PATH = "db/m4e.db"
conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys=ON")
c = conn.cursor()

print("=" * 60)
print("Applying Round 2 Fixes")
print("=" * 60)

# 1. Fix Nekima crew card
print("\n[1/3] Fix 'Nekima, Broodmother' crew card...")
c.execute("""UPDATE crew_cards 
             SET associated_master='Nekima', associated_title='Broodmother'
             WHERE id=61""")
print(f"  Updated: master='Nekima', title='Broodmother'  (rows={c.rowcount})")

# 2. Fix On Tour crew card — Wrath is a Henchman, not Master
print("\n[2/3] Fix 'On Tour' crew card...")
c.execute("""UPDATE crew_cards 
             SET associated_master='Wrath', associated_title='Henchman', faction='Neverborn'
             WHERE id=64""")
print(f"  Updated: master='Wrath', title='Henchman', faction='Neverborn'  (rows={c.rowcount})")

# 3. Create upgrade_granted_triggers table
print("\n[3/3] Create upgrade_granted_triggers table...")
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='upgrade_granted_triggers'")
if c.fetchone():
    print("  Table already exists, skipping")
else:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS upgrade_granted_triggers (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        upgrade_id      INTEGER NOT NULL,
        name            TEXT NOT NULL,
        suit            TEXT,
        timing          TEXT,
        text            TEXT NOT NULL,
        is_mandatory    BOOLEAN DEFAULT 0,
        soulstone_cost  INTEGER DEFAULT 0,
        applies_to      TEXT,
        FOREIGN KEY (upgrade_id) REFERENCES upgrades(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_upgrade_granted_triggers ON upgrade_granted_triggers(upgrade_id);
    """)
    print("  Created table + index")

conn.commit()

# Verify
print("\n--- Verification ---")
c.execute("SELECT id, name, associated_master, associated_title, faction FROM crew_cards WHERE id IN (61, 64)")
for r in c.fetchall():
    print(f"  id={r[0]} '{r[1]}' master='{r[2]}' title='{r[3]}' faction={r[4]}")

c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='upgrade_granted_triggers'")
print(f"  upgrade_granted_triggers table: {'exists' if c.fetchone() else 'MISSING'}")

print("\nDone.")
conn.close()
