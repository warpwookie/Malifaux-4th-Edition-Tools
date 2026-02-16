"""Re-export all models from DB to JSON with dual-faction support."""
import sqlite3
import json

DB_PATH = "db/m4e.db"
EXPORT_PATH = "data/all_cards_bayou.json"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()

c.execute("SELECT * FROM models ORDER BY name, title")
models = [dict(row) for row in c.fetchall()]

for model in models:
    mid = model["id"]
    c.execute("SELECT keyword FROM model_keywords WHERE model_id=?", (mid,))
    model["keywords"] = [r["keyword"] for r in c.fetchall()]
    c.execute("SELECT faction FROM model_factions WHERE model_id=?", (mid,))
    factions = [r["faction"] for r in c.fetchall()]
    model["factions"] = factions if factions else [model.get("faction", "Unknown")]
    c.execute("SELECT characteristic FROM model_characteristics WHERE model_id=?", (mid,))
    model["characteristics"] = [r["characteristic"] for r in c.fetchall()]
    c.execute("SELECT * FROM abilities WHERE model_id=? ORDER BY id", (mid,))
    model["abilities"] = [dict(r) for r in c.fetchall()]
    c.execute("SELECT * FROM actions WHERE model_id=? ORDER BY id", (mid,))
    actions = [dict(r) for r in c.fetchall()]
    for action in actions:
        c.execute("SELECT * FROM triggers WHERE action_id=? ORDER BY id", (action["id"],))
        action["triggers"] = [dict(r) for r in c.fetchall()]
    model["actions"] = actions

conn.close()

with open(EXPORT_PATH, "w", encoding="utf-8") as f:
    json.dump(models, f, indent=2)

print(f"Exported {len(models)} models to {EXPORT_PATH}")
