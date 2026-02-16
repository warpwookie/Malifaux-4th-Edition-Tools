"""
fix_factions.py — Correct model factions using source PDF paths as truth.

Each model belongs to exactly one faction, determined by the faction folder
in its source_pdf path: source_pdfs/{Faction}/{Keyword}/filename.pdf

This script:
1. Extracts the true faction from each model's source_pdf path
2. Updates models.faction where it differs
3. Rebuilds model_factions with exactly one entry per model
"""
import sqlite3
from pathlib import Path

# Map folder names to faction values
FOLDER_TO_FACTION = {
    "Arcanists": "Arcanists",
    "Bayou": "Bayou",
    "Explorer's Society": "Explorer's Society",
    "Explorers Society": "Explorer's Society",
    "Guild": "Guild",
    "Neverborn": "Neverborn",
    "Outcasts": "Outcasts",
    "Resurrectionists": "Resurrectionists",
    "Ten Thunders": "Ten Thunders",
}

def extract_faction_from_path(source_pdf):
    """Extract faction from source_pdfs/{Faction}/{Keyword}/filename.pdf"""
    if not source_pdf:
        return None
    parts = Path(source_pdf).parts
    # Find the part after "source_pdfs"
    for i, part in enumerate(parts):
        if part == "source_pdfs" and i + 1 < len(parts):
            folder = parts[i + 1]
            return FOLDER_TO_FACTION.get(folder, folder)
    return None


conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

# 1. Get all models with source_pdf
c.execute("SELECT id, name, title, faction, source_pdf FROM models ORDER BY id")
models = c.fetchall()

changes = []
no_source = []

print("Checking factions against source PDF paths...\n")

for mid, name, title, current_faction, source_pdf in models:
    true_faction = extract_faction_from_path(source_pdf)
    
    if true_faction is None:
        no_source.append((mid, name, title, current_faction))
        continue
    
    if true_faction != current_faction:
        changes.append((mid, name, title, current_faction, true_faction))

# Report changes needed
if changes:
    print(f"Faction corrections needed: {len(changes)}\n")
    for mid, name, title, old, new in changes:
        print(f"  id={mid} {name} ({title}): {old} -> {new}")
else:
    print("All factions already match source PDFs!")

if no_source:
    print(f"\nModels without source_pdf (can't verify): {len(no_source)}")
    for mid, name, title, faction in no_source[:10]:
        print(f"  id={mid} {name} ({title}) [{faction}]")
    if len(no_source) > 10:
        print(f"  ... and {len(no_source) - 10} more")

# Apply faction corrections
print(f"\nApplying {len(changes)} faction corrections...")
for mid, name, title, old, new in changes:
    c.execute("UPDATE models SET faction=? WHERE id=?", (new, mid))

# Rebuild model_factions - exactly one entry per model
print("Rebuilding model_factions (one entry per model)...")
c.execute("DELETE FROM model_factions")
c.execute("INSERT INTO model_factions (model_id, faction) SELECT id, faction FROM models")
c.execute("SELECT COUNT(*) FROM model_factions")
mf_count = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM models")
m_count = c.fetchone()[0]
print(f"  model_factions entries: {mf_count} (should equal models: {m_count})")

# Verify no duplicates
c.execute("SELECT model_id, COUNT(*) FROM model_factions GROUP BY model_id HAVING COUNT(*) > 1")
dupes = c.fetchall()
if dupes:
    print(f"  WARNING: {len(dupes)} models still have multiple faction entries!")
else:
    print("  All models have exactly one faction entry.")

conn.commit()

# Final faction distribution
print("\nFinal faction distribution:")
c.execute("SELECT faction, COUNT(*) FROM models GROUP BY faction ORDER BY faction")
for faction, count in c.fetchall():
    print(f"  {faction}: {count}")

c.execute("SELECT COUNT(*) FROM models")
print(f"\nTotal models: {c.fetchone()[0]}")

conn.close()
