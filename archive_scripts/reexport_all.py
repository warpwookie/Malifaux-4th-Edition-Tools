"""Re-export all faction JSONs from the database."""
import sys, os
sys.path.insert(0, ".")
from run_faction import export_faction_cards, faction_json_path

DB_PATH = "db/m4e.db"
FACTIONS = [
    "Bayou", "Outcasts", "Arcanists", "Guild",
    "Neverborn", "Resurrectionists", "Ten Thunders", "Explorer's Society"
]

for faction in FACTIONS:
    out = faction_json_path(faction)
    export_faction_cards(DB_PATH, out, faction)

print("\nAll faction JSONs re-exported.")
