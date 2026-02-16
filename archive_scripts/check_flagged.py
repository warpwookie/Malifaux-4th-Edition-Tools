"""Show full DB data for the 2 flagged zero-stat models."""
import sqlite3, json

conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

for model_id in [238, 784]:
    print("=" * 60)
    c.execute("SELECT * FROM models WHERE id=?", (model_id,))
    cols = [d[0] for d in c.description]
    row = c.fetchone()
    m = dict(zip(cols, row))
    
    print(f"MODEL: {m['name']} ({m.get('title')})")
    print(f"  ID: {m['id']}, Faction: {m['faction']}, Station: {m['station']}")
    print(f"  Stats: Df={m['df']} Wp={m['wp']} Sz={m['sz']} Sp={m['sp']} Health={m['health']}")
    print(f"  Cost: {m.get('cost')}, Base: {m.get('base_size')}")
    print(f"  Soulstone: {m.get('soulstone_cache')}, Shields: {m.get('shields')}")
    print(f"  Source: {m.get('source_pdf')}")
    
    print(f"\n  Keywords:")
    c.execute("SELECT keyword FROM model_keywords WHERE model_id=?", (model_id,))
    for r in c.fetchall():
        print(f"    {r[0]}")
    
    print(f"\n  Characteristics:")
    c.execute("SELECT characteristic FROM model_characteristics WHERE model_id=?", (model_id,))
    for r in c.fetchall():
        print(f"    {r[0]}")
    
    print(f"\n  Abilities:")
    c.execute("SELECT name, text FROM abilities WHERE model_id=?", (model_id,))
    for r in c.fetchall():
        print(f"    {r[0]}: {r[1][:80]}...")
    
    print(f"\n  Actions:")
    c.execute("SELECT id, name, category, action_type, range, skill_value, resist, tn, damage FROM actions WHERE model_id=?", (model_id,))
    for r in c.fetchall():
        print(f"    [{r[2]}] {r[1]}: type={r[3]} rg={r[4]} skill={r[5]} resist={r[6]} tn={r[7]} dmg={r[8]}")
        c.execute("SELECT name, suit, timing FROM triggers WHERE action_id=?", (r[0],))
        for t in c.fetchall():
            print(f"      trigger: {t[1]} {t[0]} ({t[2]})")
    
    print()

conn.close()
