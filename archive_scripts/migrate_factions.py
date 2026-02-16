"""
Migration: Add model_factions junction table for dual-faction support.

Run this ONCE against your existing database to:
1. Create the model_factions table
2. Populate it from existing models
3. All models get 'Bayou' (since they came from Bayou PDFs)
4. Models with a different detected faction also get that faction

Safe to run multiple times (uses IF NOT EXISTS / INSERT OR IGNORE).
"""
import sqlite3

DB_PATH = "db/m4e.db"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Create junction table
c.execute("""
    CREATE TABLE IF NOT EXISTS model_factions (
        model_id    INTEGER NOT NULL,
        faction     TEXT NOT NULL,
        FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE,
        UNIQUE(model_id, faction)
    )
""")

# Create index
c.execute("CREATE INDEX IF NOT EXISTS idx_model_factions_faction ON model_factions(faction)")

# Populate from existing models
c.execute("SELECT id, name, title, faction FROM models")
models = c.fetchall()

added = 0
for model_id, name, title, faction in models:
    # Every model in this DB is Bayou-playable
    c.execute("INSERT OR IGNORE INTO model_factions (model_id, faction) VALUES (?, ?)",
              (model_id, "Bayou"))
    added += c.rowcount
    
    # If detected faction differs, add that too (dual-faction)
    if faction and faction != "Bayou":
        c.execute("INSERT OR IGNORE INTO model_factions (model_id, faction) VALUES (?, ?)",
                  (model_id, faction))
        added += c.rowcount

conn.commit()

# Report
c.execute("SELECT COUNT(DISTINCT model_id) FROM model_factions")
total_models = c.fetchone()[0]
c.execute("SELECT faction, COUNT(*) FROM model_factions GROUP BY faction ORDER BY faction")
print(f"Migration complete. {total_models} models with faction tags:")
for faction, count in c.fetchall():
    print(f"  {faction}: {count}")

# Show dual-faction models
c.execute("""
    SELECT m.name, m.title, GROUP_CONCAT(mf.faction, ', ') as factions
    FROM models m
    JOIN model_factions mf ON m.id = mf.model_id
    GROUP BY m.id
    HAVING COUNT(mf.faction) > 1
    ORDER BY m.name
""")
duals = c.fetchall()
if duals:
    print(f"\nDual-faction models ({len(duals)}):")
    for name, title, factions in duals:
        label = f"{name} ({title})" if title else name
        print(f"  {label}: {factions}")

conn.close()
