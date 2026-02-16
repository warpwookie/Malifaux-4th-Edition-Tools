import sqlite3

conn = sqlite3.connect("db/m4e.db")
c = conn.cursor()

# 1. Set Jebediah's "Lost My Hat!" to Tome
c.execute("""UPDATE triggers SET suit='(t)' 
             WHERE name='"Lost My Hat!"' AND suit IS NULL""")
print(f"Set 'Lost My Hat!' suit to (t): {c.rowcount} row(s)")

# 2. Delete Delirium's misparsed "triggers" (they're selectable effects, not triggers)
for name in ['Acrophobia', 'Agoraphobia', 'Monophobia']:
    c.execute("""DELETE FROM triggers WHERE name=? 
                 AND action_id IN (SELECT a.id FROM actions a 
                                   JOIN models m ON a.model_id=m.id 
                                   WHERE m.name='Delirium')""", (name,))
    print(f"Deleted '{name}': {c.rowcount} row(s)")

# Verify
c.execute("SELECT COUNT(*) FROM triggers WHERE suit IS NULL OR suit=''")
print(f"\nRemaining null-suit triggers: {c.fetchone()[0]}")

conn.commit()
conn.close()
