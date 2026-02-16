"""
fix_totem_links.py — Link Masters to their Totems.

Strategy: For each Master missing a totem, check if any of their keywords
match a Totem model's name in the DB. If so, set the totem field.

Also checks cross-faction (some Masters/Totems span factions via model_factions).
"""
import sqlite3

conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

# Get all Totems: name -> list of factions
c.execute("""SELECT m.id, m.name, m.title, m.faction,
             GROUP_CONCAT(DISTINCT mk.keyword) as keywords
             FROM models m
             LEFT JOIN model_keywords mk ON m.id = mk.model_id
             WHERE m.station = 'Totem'
             GROUP BY m.id""")
totems = {}
for tid, tname, ttitle, tfaction, tkeywords in c.fetchall():
    key = tname.lower()
    if key not in totems:
        totems[key] = []
    totems[key].append({
        "id": tid, "name": tname, "title": ttitle,
        "faction": tfaction, "keywords": tkeywords
    })
    # Also index with title for cases like "Lord Chompy Bits (Dreamlord)"
    if ttitle:
        full = f"{tname} ({ttitle})".lower()
        if full not in totems:
            totems[full] = []
        totems[full].append({
            "id": tid, "name": tname, "title": ttitle,
            "faction": tfaction, "keywords": tkeywords
        })

# Get Masters with no totem and their keywords
c.execute("""SELECT m.id, m.name, m.title, m.faction,
             GROUP_CONCAT(mk.keyword) as keywords
             FROM models m
             LEFT JOIN model_keywords mk ON m.id = mk.model_id
             WHERE m.station = 'Master' AND (m.totem IS NULL OR m.totem = '')
             GROUP BY m.id
             ORDER BY m.faction, m.name""")

masters = c.fetchall()
print(f"Masters needing totems: {len(masters)}\n")

linked = 0
unlinked = []

for mid, mname, mtitle, mfaction, mkeywords in masters:
    if not mkeywords:
        unlinked.append((mid, mname, mtitle, mfaction, "no keywords"))
        continue
    
    keywords = [k.strip() for k in mkeywords.split(",")]
    matched_totem = None
    
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower in totems:
            # Found a match - prefer same faction
            candidates = totems[kw_lower]
            same_faction = [t for t in candidates if t["faction"] == mfaction]
            if same_faction:
                matched_totem = same_faction[0]["name"]
            else:
                # Cross-faction totem
                matched_totem = candidates[0]["name"]
            break
    
    if matched_totem:
        c.execute("UPDATE models SET totem=? WHERE id=?", (matched_totem, mid))
        print(f"  {mname} ({mtitle}) [{mfaction}] -> totem: {matched_totem}")
        linked += 1
    else:
        unlinked.append((mid, mname, mtitle, mfaction, mkeywords))

print(f"\nLinked: {linked}")
print(f"Unlinked: {len(unlinked)}")

if unlinked:
    print("\nStill need totems:")
    for mid, name, title, faction, kws in unlinked:
        print(f"  id={mid} {name} ({title}) [{faction}] — keywords: {kws}")

# Final count
c.execute("""SELECT COUNT(*) FROM models 
             WHERE station='Master' AND (totem IS NULL OR totem='')""")
print(f"\nMasters still missing totem: {c.fetchone()[0]}")

conn.commit()
conn.close()
