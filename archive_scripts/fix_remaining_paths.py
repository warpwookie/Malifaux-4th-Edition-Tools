import sqlite3
from pathlib import Path

# Find the actual files
source = Path("source_pdfs")

print("Searching for unmatched models...\n")

# Drumstick
for p in source.rglob("*Drum*"):
    print(f"  Drumstick? {p.name}")
for p in source.rglob("*Big_Hat_Jockey*"):
    print(f"  Drumstick? {p.name}")

# Habber-Dasher
for p in source.rglob("*Habber*"):
    print(f"  Habber-Dasher? {p.name}")

# Som'er
for p in source.rglob("*Somer*"):
    print(f"  Som'er? {p.name}")
for p in source.rglob("*Som*"):
    if "Stat" in p.name:
        print(f"  Som'er? {p.name}")

print()

# Apply fixes based on what we find
conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

fixes = [
    (27, "Drumstick", str(next(source.rglob("*Big_Hat_Jockey_Drunstick*"), None) or "")),
    (2, "Habber-Dasher", str(next(source.rglob("*Habber_Dasher*"), None) or "")),
    (1, "Som'er (Loot Monger)", str(next(source.rglob("*Somer*Loot*"), None) or "")),
    (16, "Som'er (Bayou Boss)", str(next(source.rglob("*Somer*Bayou_Boss*"), None) or "")),
]

for mid, name, path in fixes:
    if path:
        c.execute("UPDATE models SET source_pdf=? WHERE id=?", (path, mid))
        print(f"  id={mid} {name} -> {Path(path).name}")
    else:
        print(f"  id={mid} {name} -> NOT FOUND")

conn.commit()
c.execute("SELECT COUNT(*) FROM models WHERE source_pdf IS NULL OR source_pdf=''")
print(f"\nRemaining without source_pdf: {c.fetchone()[0]}")
conn.close()
