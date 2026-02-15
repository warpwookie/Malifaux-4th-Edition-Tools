"""
fix_duplicates.py — Merge duplicate models caused by name casing differences
or cross-faction re-extraction.

For each pair: keeps the model with more data (more actions/abilities),
normalizes the name, merges faction links, deletes the duplicate.

Usage:
  python fix_duplicates.py              # Preview
  python fix_duplicates.py --apply      # Apply merges
"""
import sqlite3, sys

DRY_RUN = "--apply" not in sys.argv
DB_PATH = "db/m4e.db"

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys=ON")
conn.row_factory = sqlite3.Row
c = conn.cursor()


def model_richness(model_id):
    """Score how much data a model has (more = better to keep)."""
    ab = c.execute("SELECT COUNT(*) FROM abilities WHERE model_id=?", (model_id,)).fetchone()[0]
    ac = c.execute("SELECT COUNT(*) FROM actions WHERE model_id=?", (model_id,)).fetchone()[0]
    tr = sum(
        r[0] for r in c.execute(
            "SELECT COUNT(*) FROM triggers WHERE action_id IN "
            "(SELECT id FROM actions WHERE model_id=?)", (model_id,)
        ).fetchall()
    )
    return ab + ac + tr


def get_factions(model_id):
    """Get all factions for a model from junction table."""
    return [r[0] for r in c.execute(
        "SELECT faction FROM model_factions WHERE model_id=?", (model_id,)
    ).fetchall()]


def merge_pair(keep_id, delete_id, canonical_name, reason):
    """Merge delete_id into keep_id: transfer factions, update name, delete duplicate."""
    keep_factions = set(get_factions(keep_id))
    delete_factions = set(get_factions(delete_id))
    all_factions = keep_factions | delete_factions

    print(f"  Keep id={keep_id}, delete id={delete_id}")
    print(f"    Name -> '{canonical_name}'")
    print(f"    Factions: {sorted(all_factions)}")

    if DRY_RUN:
        return

    # Update name on keeper
    c.execute("UPDATE models SET name=? WHERE id=?", (canonical_name, keep_id))

    # Merge factions
    for fac in all_factions:
        c.execute("INSERT OR IGNORE INTO model_factions (model_id, faction) VALUES (?,?)",
                  (keep_id, fac))

    # Delete the duplicate's faction links, then the model itself
    c.execute("DELETE FROM model_factions WHERE model_id=?", (delete_id,))
    c.execute("DELETE FROM model_keywords WHERE model_id=?", (delete_id,))
    c.execute("DELETE FROM model_characteristics WHERE model_id=?", (delete_id,))
    c.execute("DELETE FROM abilities WHERE model_id=?", (delete_id,))
    # Triggers first (FK to actions)
    for (aid,) in c.execute("SELECT id FROM actions WHERE model_id=?", (delete_id,)).fetchall():
        c.execute("DELETE FROM triggers WHERE action_id=?", (aid,))
    c.execute("DELETE FROM actions WHERE model_id=?", (delete_id,))
    c.execute("DELETE FROM models WHERE id=?", (delete_id,))


# ── Define duplicate pairs ──────────────────────────────────────────
# (id_a, id_b, canonical_name, reason)
# We'll score richness to decide which to keep

DUPLICATES = [
    # Same-faction casing duplicates
    (91, 123, "Bandido", "casing"),
    (162, 452, "Hooded Rider", "casing"),
    (47, 466, "Leech King", "casing"),
    (100, 125, "Six Armed Six-Shooter", "casing"),
    (126, 28, "Toast", "casing"),
    # Cross-faction duplicates (same model, different source factions)
    (219, 4, "Bashe", "cross-faction"),
    (295, 218, "Clipper", "cross-faction"),
    (221, 414, "Ferdinand Vogel", "cross-faction"),
    (212, 122, "Mechanical Rider", "cross-faction"),
    (99, 124, "Pearl Musgrove", "cross-faction"),
]

print(f"Duplicate pairs to merge: {len(DUPLICATES)}\n")

merged = 0
for id_a, id_b, canonical, reason in DUPLICATES:
    # Verify both exist
    a_exists = c.execute("SELECT name, faction FROM models WHERE id=?", (id_a,)).fetchone()
    b_exists = c.execute("SELECT name, faction FROM models WHERE id=?", (id_b,)).fetchone()

    if not a_exists or not b_exists:
        name_a = a_exists["name"] if a_exists else "MISSING"
        name_b = b_exists["name"] if b_exists else "MISSING"
        print(f"SKIP: {canonical} — id={id_a}({name_a}) / id={id_b}({name_b}) — one missing")
        continue

    score_a = model_richness(id_a)
    score_b = model_richness(id_b)

    # Keep the richer model (ties: keep lower id = earlier insert)
    if score_a >= score_b:
        keep_id, delete_id = id_a, id_b
    else:
        keep_id, delete_id = id_b, id_a

    print(f"{canonical} ({reason})")
    print(f"  id={id_a} '{a_exists['name']}' [{a_exists['faction']}] score={score_a}")
    print(f"  id={id_b} '{b_exists['name']}' [{b_exists['faction']}] score={score_b}")

    merge_pair(keep_id, delete_id, canonical, reason)
    merged += 1
    print()

if not DRY_RUN:
    conn.commit()
    print(f"Done — {merged} pairs merged.")
    print("Re-export faction JSONs to pick up changes.")
else:
    print(f"Dry run — {merged} pairs would be merged. Use --apply to execute.")

conn.close()
