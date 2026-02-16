"""
fix_completeness.py — Fix completeness gaps that can be inferred from existing data.

1. Infer stations from characteristics (Minion/Peon in characteristics table)
2. Infer keywords from source_pdf folder paths
3. Link Masters to crew cards via name matching
4. Infer stations from cost/characteristics heuristics for remaining models
5. Update audit exclusion for On Tour (Henchman crew card)

Usage:
    python fix_completeness.py              # Preview
    python fix_completeness.py --apply      # Apply
"""
import sqlite3
import sys
import re
from pathlib import Path
from collections import defaultdict

DRY_RUN = "--apply" not in sys.argv
DB_PATH = "db/m4e.db"

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys=ON")
c = conn.cursor()

total_fixed = 0

print("=" * 70)
print("COMPLETENESS FIXES")
print("=" * 70)

# ============================================================
# 1. INFER STATION FROM CHARACTERISTICS
# ============================================================
print("\n[1/5] Inferring stations from characteristics...")

STATION_CHARS = ["Master", "Henchman", "Enforcer", "Minion", "Totem", "Peon"]

fixed_station_1 = 0
for station in STATION_CHARS:
    c.execute("""SELECT m.id, m.name, m.title FROM models m
                 JOIN model_characteristics mc ON m.id = mc.model_id
                 WHERE m.station IS NULL AND mc.characteristic = ?""", (station,))
    matches = c.fetchall()
    if matches:
        print(f"  {station}: {len(matches)} models")
        for mid, name, title in matches:
            print(f"    id={mid} {name} ({title}) -> {station}")
            if not DRY_RUN:
                c.execute("UPDATE models SET station=? WHERE id=?", (station, mid))
            fixed_station_1 += 1

if fixed_station_1 == 0:
    print("  No stations to infer from characteristics")
else:
    print(f"  Subtotal: {fixed_station_1} stations inferred")
    total_fixed += fixed_station_1

# ============================================================
# 2. INFER KEYWORDS FROM SOURCE PDF PATHS
# ============================================================
print("\n[2/5] Inferring keywords from source PDF paths...")

# Folder name -> keyword mapping for special cases
FOLDER_KEYWORD_MAP = {
    "Versatile": "Versatile",
    "Versatile - Neverborn": "Versatile",
    "Versatile - Ten Thunders": "Versatile",
    "Versatile - Explorer's Society": "Versatile",
    "Versatile - Guild": "Versatile",
    "Versatile - Outcasts": "Versatile",
    "Versatile - Resurrectionists": "Versatile",
    "Versatile - Arcanists": "Versatile",
    "ByuVersatile": "Versatile",
    "Big Hat": "Big Hat",
    "Big_Hat": "Big Hat",
    "BigHat": "Big Hat",
    "Tri-Chi": "Tri-Chi",
    "TriChi": "Tri-Chi",
    "Wizz-Bang": "Wizz-Bang",
    "WizzBang": "Wizz-Bang",
    "Wizz_Bang": "Wizz-Bang",
}

c.execute("""SELECT m.id, m.name, m.title, m.source_pdf FROM models m
             WHERE NOT EXISTS (SELECT 1 FROM model_keywords WHERE model_id=m.id)
             AND m.source_pdf IS NOT NULL""")
no_kw_models = c.fetchall()

fixed_kw = 0
kw_errors = 0
for mid, name, title, source_pdf in no_kw_models:
    p = Path(source_pdf)
    parts = p.parts
    
    # Find the keyword folder (parent of the PDF, child of faction folder)
    # Pattern: source_pdfs/{Faction}/{Keyword}/M4E_Stat_...
    keyword = None
    for i, part in enumerate(parts):
        if part == "source_pdfs" and i + 2 < len(parts):
            folder_name = parts[i + 2]
            # Check mapped names first
            if folder_name in FOLDER_KEYWORD_MAP:
                keyword = FOLDER_KEYWORD_MAP[folder_name]
            else:
                # Clean up folder name: underscores to spaces, etc.
                keyword = folder_name.replace("_", " ")
                # Handle common patterns
                keyword = re.sub(r'^(Byu|Gld|Nvb|Out|Res|TT|Exs|Arc)', '', keyword).strip()
                if keyword.startswith("Versatile"):
                    keyword = "Versatile"
            break
    
    if not keyword:
        kw_errors += 1
        continue
    
    # Check if this keyword already exists for this model
    c.execute("SELECT 1 FROM model_keywords WHERE model_id=? AND keyword=?", (mid, keyword))
    if c.fetchone():
        continue
    
    print(f"  id={mid} {name} ({title}) -> keyword '{keyword}'")
    if not DRY_RUN:
        c.execute("INSERT INTO model_keywords (model_id, keyword) VALUES (?,?)", (mid, keyword))
    fixed_kw += 1

print(f"  Keywords added: {fixed_kw}")
if kw_errors:
    print(f"  Could not determine keyword: {kw_errors}")
total_fixed += fixed_kw

# ============================================================
# 3. LINK MASTERS TO CREW CARDS
# ============================================================
print("\n[3/5] Linking Masters to crew cards...")

c.execute("""SELECT m.id, m.name, m.title, m.faction FROM models m
             WHERE m.station='Master' AND (m.crew_card_name IS NULL OR m.crew_card_name='')""")
masters_no_crew = c.fetchall()

fixed_crew = 0
for mid, name, title, faction in masters_no_crew:
    # Find crew cards that match this master
    c.execute("""SELECT id, name FROM crew_cards 
                 WHERE associated_master = ?
                 ORDER BY id""", (name,))
    matches = c.fetchall()
    
    if not matches:
        # Try partial match
        c.execute("""SELECT id, name FROM crew_cards 
                     WHERE associated_master LIKE ? OR name LIKE ?
                     ORDER BY id""", (f"%{name}%", f"%{name}%"))
        matches = c.fetchall()
    
    if matches:
        crew_names = ", ".join(m[1] for m in matches)
        print(f"  id={mid} {name} ({title}) -> crew cards: {crew_names}")
        if not DRY_RUN:
            # Store the first crew card name (they can look up others via the crew_cards table)
            c.execute("UPDATE models SET crew_card_name=? WHERE id=?", (matches[0][1], mid))
        fixed_crew += 1
    else:
        print(f"  id={mid} {name} ({title}) -> NO MATCHING CREW CARD")

print(f"  Masters linked: {fixed_crew}")
total_fixed += fixed_crew

# ============================================================
# 4. INFER REMAINING STATIONS FROM COST + CHARACTERISTICS
# ============================================================
print("\n[4/5] Inferring remaining stations from cost heuristics...")

# In M4E:
# - Cost '-' = Master or Totem
# - Totems typically have "Totem" in name or characteristics, or Effigy
# - Cost 0-3 with no "Master"/"Totem" = likely Peon
# - Models with "Unique" and cost 6-10 = Henchman or Enforcer (can't distinguish reliably)
# - Non-unique models with "Minion(N)" pattern = Minion

c.execute("""SELECT m.id, m.name, m.title, m.cost, m.faction,
             GROUP_CONCAT(mc.characteristic, '|') as chars
             FROM models m
             LEFT JOIN model_characteristics mc ON m.id = mc.model_id
             WHERE m.station IS NULL
             GROUP BY m.id""")
null_station = c.fetchall()

fixed_station_2 = 0
uncertain = []
for mid, name, title, cost, faction, chars_str in null_station:
    chars = set((chars_str or "").split("|"))
    inferred = None
    confidence = "low"
    
    # Cost '-' models
    if cost == '-' or cost is None:
        if "Effigy" in chars or "Totem" in name.lower():
            inferred = "Totem"
            confidence = "high"
        elif "Master" in chars:
            inferred = "Master"
            confidence = "high"
        else:
            # Cost dash, not clearly totem or master — skip
            uncertain.append((mid, name, title, cost, chars))
            continue
    
    # Effigy characteristic = Totem
    elif "Effigy" in chars:
        inferred = "Totem"
        confidence = "high"
    
    # Emissary models are Henchman
    elif "Emissary" in (title or ""):
        inferred = "Henchman"
        confidence = "high"
    
    # Rider models are typically Henchman
    elif "Rider" in (name or "") and "Unique" in chars:
        inferred = "Henchman"
        confidence = "medium"
    
    # If it's not unique and has a numeric cost, likely Minion
    # (non-unique models in M4E are almost always Minions)
    elif "Unique" not in chars and cost and cost != '-':
        try:
            cost_val = int(cost)
            if cost_val >= 1:
                inferred = "Minion"
                confidence = "high"
        except ValueError:
            pass
    
    if inferred and confidence in ("high", "medium"):
        print(f"  id={mid} {name} ({title}) cost={cost} -> {inferred} [{confidence}]")
        if not DRY_RUN:
            c.execute("UPDATE models SET station=? WHERE id=?", (inferred, mid))
        fixed_station_2 += 1
    else:
        uncertain.append((mid, name, title, cost, chars))

print(f"  Stations inferred: {fixed_station_2}")
if uncertain:
    print(f"  Still uncertain: {len(uncertain)} models (Unique, cost-based, need manual review)")
    for mid, name, title, cost, chars in uncertain[:15]:
        print(f"    id={mid} {name} ({title}) cost={cost} chars={chars}")
    if len(uncertain) > 15:
        print(f"    ... and {len(uncertain) - 15} more")
total_fixed += fixed_station_2

# ============================================================
# 5. FIX ON TOUR AUDIT (update audit to handle Henchman crew cards)
# ============================================================
print("\n[5/5] On Tour crew card status...")
c.execute("""SELECT id, name, associated_master, associated_title FROM crew_cards WHERE name='On Tour'""")
r = c.fetchone()
if r:
    print(f"  id={r[0]} '{r[1]}' master='{r[2]}' title='{r[3]}'")
    print(f"  This is a Henchman crew card — audit rule is too strict, not a data error.")

# ============================================================
# SUMMARY
# ============================================================
if not DRY_RUN:
    conn.commit()

print("\n" + "=" * 70)
print(f"TOTAL FIXES: {total_fixed}")
print(f"  Stations from characteristics: {fixed_station_1}")
print(f"  Keywords from folder paths: {fixed_kw}")
print(f"  Masters linked to crew cards: {fixed_crew}")
print(f"  Stations from cost heuristics: {fixed_station_2}")
if DRY_RUN:
    print("\nDry run — use --apply to make changes.")
print("=" * 70)

conn.close()
