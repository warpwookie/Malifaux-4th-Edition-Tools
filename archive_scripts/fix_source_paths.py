"""
fix_source_paths.py — Find and link source PDFs for models missing source_pdf.
Also handles remaining trigger suits and stations.
"""
import sqlite3
import re
from pathlib import Path

conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

SOURCE_DIR = Path("source_pdfs")

# Get models with null source_pdf
c.execute("""SELECT id, name, title, faction FROM models 
             WHERE source_pdf IS NULL OR source_pdf = ''
             ORDER BY faction, name""")
missing = c.fetchall()
print(f"Models with no source_pdf: {len(missing)}\n")

# Build index of all stat PDFs
pdf_index = {}
for pdf in SOURCE_DIR.rglob("M4E_Stat_*.pdf"):
    # Extract model name from filename
    # Pattern: M4E_Stat_{Keyword}_{ModelName}[_{Variant}].pdf
    stem = pdf.stem
    # Remove M4E_Stat_ prefix and variant suffix
    parts = stem.split("_")
    # Skip first 2 parts (M4E, Stat), skip keyword part
    if len(parts) >= 4:
        # Reconstruct possible model name
        name_parts = parts[2:]  # after M4E_Stat_
        # Remove variant suffix (single letter at end like _A, _B, _C)
        if len(name_parts[-1]) == 1 and name_parts[-1].isalpha():
            name_parts = name_parts[:-1]
        name_key = " ".join(name_parts).lower()
        # Also try without keyword
        if len(parts) >= 5:
            name_parts_no_kw = parts[3:]
            if len(name_parts_no_kw[-1]) == 1 and name_parts_no_kw[-1].isalpha():
                name_parts_no_kw = name_parts_no_kw[:-1]
            name_key_no_kw = " ".join(name_parts_no_kw).lower()
            pdf_index[name_key_no_kw] = str(pdf)
        pdf_index[name_key] = str(pdf)

# Try to match
found = 0
not_found = []
for mid, name, title, faction in missing:
    # Normalize name for matching
    search_name = name.lower().replace("'", "").replace("'", "").replace(",", "").replace(".", "")
    search_name = re.sub(r'\s+', ' ', search_name).strip()
    
    # Try exact match
    match = pdf_index.get(search_name)
    
    # Try with underscores
    if not match:
        search_us = search_name.replace(" ", "_")
        for key, path in pdf_index.items():
            if search_us in key.replace(" ", "_") or key.replace(" ", "_") in search_us:
                match = path
                break
    
    # Try partial match
    if not match:
        name_words = search_name.split()
        for key, path in pdf_index.items():
            key_words = key.split()
            # Check if all significant words match
            if len(name_words) >= 2 and all(w in key for w in name_words[:2]):
                match = path
                break
    
    if match:
        print(f"  FOUND id={mid} {name} ({title}) -> {Path(match).name}")
        c.execute("UPDATE models SET source_pdf=? WHERE id=?", (match, mid))
        found += 1
    else:
        not_found.append((mid, name, title, faction))

print(f"\nMatched: {found}")
print(f"Not found: {len(not_found)}")
if not_found:
    print("\nUnmatched models:")
    for mid, name, title, faction in not_found:
        print(f"  id={mid} {name} ({title}) [{faction}]")

conn.commit()
conn.close()
