"""
fix_audit_errors.py — Fix errors found by final_audit.py

1. Merge Bo Peep and Slop Hauler duplicates
2. Flag zero-stat models for investigation
3. Check empty upgrades
4. Normalize action categories ('attack' -> 'attack_actions', etc.)

Usage:
    python fix_audit_errors.py              # Preview
    python fix_audit_errors.py --apply      # Apply fixes
"""
import sqlite3
import sys

DRY_RUN = "--apply" not in sys.argv
DB_PATH = "db/m4e.db"

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys=ON")
c = conn.cursor()

print("=" * 60)
print("Fixing audit errors")
print("=" * 60)

# ============================================================
# 1. DUPLICATE MERGES — Bo Peep, Slop Hauler
# ============================================================
print("\n[1/4] Duplicate merges...")

DUPES = [
    ("Bo Peep", None, "Bayou"),
    ("Slop Hauler", None, "Bayou"),
]

for name, title, faction in DUPES:
    if title:
        c.execute("SELECT id FROM models WHERE name=? AND title=? AND faction=? ORDER BY id",
                  (name, title, faction))
    else:
        c.execute("SELECT id FROM models WHERE name=? AND title IS NULL AND faction=? ORDER BY id",
                  (name, faction))
    rows = c.fetchall()
    
    if len(rows) < 2:
        print(f"  SKIP {name}: no duplicate found ({len(rows)} entries)")
        continue
    
    keep_id = rows[0][0]
    remove_id = rows[1][0]
    
    # Score richness
    for mid in [keep_id, remove_id]:
        c.execute("SELECT COUNT(*) FROM abilities WHERE model_id=?", (mid,))
        ab = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM actions WHERE model_id=?", (mid,))
        act = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM triggers t JOIN actions a ON t.action_id=a.id WHERE a.model_id=?", (mid,))
        trig = c.fetchone()[0]
        score = ab + act + trig
        if mid == keep_id:
            keep_score = score
        else:
            remove_score = score
    
    # Keep the richer one
    if remove_score > keep_score:
        keep_id, remove_id = remove_id, keep_id
        keep_score, remove_score = remove_score, keep_score
    
    print(f"  {name}: keep id={keep_id} (score={keep_score}), remove id={remove_id} (score={remove_score})")
    
    if not DRY_RUN:
        # Move any faction links
        try:
            c.execute("UPDATE OR IGNORE model_factions SET model_id=? WHERE model_id=?",
                      (keep_id, remove_id))
            c.execute("DELETE FROM model_factions WHERE model_id=?", (remove_id,))
        except:
            pass
        
        # Delete duplicate's child records
        c.execute("DELETE FROM abilities WHERE model_id=?", (remove_id,))
        c.execute("SELECT id FROM actions WHERE model_id=?", (remove_id,))
        for (aid,) in c.fetchall():
            c.execute("DELETE FROM triggers WHERE action_id=?", (aid,))
        c.execute("DELETE FROM actions WHERE model_id=?", (remove_id,))
        c.execute("DELETE FROM model_keywords WHERE model_id=?", (remove_id,))
        c.execute("DELETE FROM model_characteristics WHERE model_id=?", (remove_id,))
        c.execute("DELETE FROM models WHERE id=?", (remove_id,))
        print(f"    DELETED id={remove_id}")

# ============================================================
# 2. ZERO-STAT MODELS — flag for review
# ============================================================
print("\n[2/4] Zero-stat models...")

c.execute("""SELECT id, name, title, df, wp, sz, sp, health, source_pdf 
             FROM models WHERE wp=0 OR health=0""")
zero_stats = c.fetchall()
for row in zero_stats:
    mid, name, title, df, wp, sz, sp, hp, src = row
    issues = []
    if wp == 0: issues.append("wp=0")
    if hp == 0: issues.append("health=0")
    print(f"  id={mid} {name} ({title}): {', '.join(issues)}")
    print(f"    Stats: df={df} wp={wp} sz={sz} sp={sp} hp={hp}")
    print(f"    Source: {src}")
    
    if not DRY_RUN:
        c.execute("UPDATE models SET parse_status='flagged' WHERE id=?", (mid,))
        print(f"    FLAGGED for manual review")

# ============================================================
# 3. EMPTY UPGRADES — check what happened
# ============================================================
print("\n[3/4] Empty upgrades...")

c.execute("""SELECT u.id, u.name, u.keyword, u.faction, u.source_pdf FROM upgrades u
             WHERE NOT EXISTS (SELECT 1 FROM upgrade_abilities WHERE upgrade_id=u.id)
             AND NOT EXISTS (SELECT 1 FROM upgrade_actions WHERE upgrade_id=u.id)""")
empty_upgrades = c.fetchall()
for row in empty_upgrades:
    uid, name, keyword, faction, src = row
    print(f"  id={uid} {name} [{faction}/{keyword}]")
    # Check if it has a description at least
    c.execute("SELECT description, limitations, upgrade_type FROM upgrades WHERE id=?", (uid,))
    desc, lim, utype = c.fetchone()
    print(f"    Type: {utype}, Limitations: {lim}")
    print(f"    Description: {(desc or '')[:80]}...")
    
    if not DRY_RUN:
        c.execute("UPDATE upgrades SET parse_status='flagged' WHERE id=?", (uid,))
        print(f"    FLAGGED for re-extraction")

# ============================================================
# 4. NORMALIZE ACTION CATEGORIES
# ============================================================
print("\n[4/4] Normalizing action categories...")

# Fix 'attack' -> 'attack_actions'
c.execute("SELECT COUNT(*) FROM actions WHERE category='attack'")
attack_count = c.fetchone()[0]
if attack_count > 0:
    print(f"  {attack_count} actions with category='attack' -> 'attack_actions'")
    if not DRY_RUN:
        c.execute("UPDATE actions SET category='attack_actions' WHERE category='attack'")

# Fix 'tactical' -> 'tactical_actions'
c.execute("SELECT COUNT(*) FROM actions WHERE category='tactical'")
tactical_count = c.fetchone()[0]
if tactical_count > 0:
    print(f"  {tactical_count} actions with category='tactical' -> 'tactical_actions'")
    if not DRY_RUN:
        c.execute("UPDATE actions SET category='tactical_actions' WHERE category='tactical'")

if attack_count == 0 and tactical_count == 0:
    print("  No category normalization needed")

# Also check upgrade actions
try:
    c.execute("SELECT COUNT(*) FROM upgrade_actions WHERE category='attack'")
    ua = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM upgrade_actions WHERE category='tactical'")
    ut = c.fetchone()[0]
    if ua > 0:
        print(f"  {ua} upgrade actions 'attack' -> 'attack_actions'")
        if not DRY_RUN:
            c.execute("UPDATE upgrade_actions SET category='attack_actions' WHERE category='attack'")
    if ut > 0:
        print(f"  {ut} upgrade actions 'tactical' -> 'tactical_actions'")
        if not DRY_RUN:
            c.execute("UPDATE upgrade_actions SET category='tactical_actions' WHERE category='tactical'")
except:
    pass

# Commit
if not DRY_RUN:
    conn.commit()
    c.execute("SELECT COUNT(*) FROM models")
    print(f"\nFinal model count: {c.fetchone()[0]}")
    print("All fixes applied.")
else:
    print(f"\nDry run — use --apply to fix.")

conn.close()
