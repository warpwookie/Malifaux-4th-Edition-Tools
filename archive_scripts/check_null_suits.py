import sqlite3
c = sqlite3.connect("db/m4e.db").cursor()
c.execute("""SELECT t.name, t.suit, t.timing, t.text, a.name as action_name, m.name
             FROM triggers t 
             JOIN actions a ON t.action_id = a.id 
             JOIN models m ON a.model_id = m.id 
             WHERE t.suit IS NULL OR t.suit = ''""")
for r in c.fetchall():
    print(f"{r[5]} / {r[4]} -> {r[0]}: timing={r[2]}")
    print(f"  text: {r[3][:100]}")
    print()
