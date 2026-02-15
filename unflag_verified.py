import sqlite3
c = sqlite3.connect("db/m4e.db")
c.execute("UPDATE models SET parse_status='verified' WHERE id IN (238, 784)")
c.commit()
print("Clockwork Trap and Marathine marked as verified.")
c.close()
