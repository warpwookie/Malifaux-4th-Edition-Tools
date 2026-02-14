"""Quick diagnostic: check parse log and validation results."""
import sqlite3
import json
import os
import glob

DB_PATH = "db/m4e.db"
WORK_DIR = "pipeline_work"

print("=" * 60)
print("PARSE LOG SUMMARY")
print("=" * 60)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("""
    SELECT model_name, status, hard_rule_violations, soft_rule_flags 
    FROM parse_log 
    ORDER BY status, model_name
""")

for row in c.fetchall():
    name, status, hard, soft = row
    print(f"\n  [{status}] {name}")
    if hard:
        violations = json.loads(hard)
        for v in violations:
            print(f"    HARD: {v}")
    if soft:
        flags = json.loads(soft)
        for f in flags:
            print(f"    soft: {f}")

conn.close()

print("\n" + "=" * 60)
print("FAILED CARD FILES")
print("=" * 60)

for f in glob.glob(os.path.join(WORK_DIR, "*FAILED*")):
    print(f"\n  {os.path.basename(f)}")
    with open(f, encoding="utf-8") as fh:
        data = json.load(fh)
        if "validation" in data:
            v = data["validation"]
            print(f"    Hard violations: {v.get('hard_rule_violations', [])}")
            print(f"    Soft flags: {v.get('soft_rule_flags', [])}")

print("\n" + "=" * 60)
print("DB MODEL COUNT")
print("=" * 60)
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute("SELECT COUNT(*) FROM models")
print(f"  Models: {c.fetchone()[0]}")
c.execute("SELECT COUNT(*) FROM crew_cards")
print(f"  Crew cards: {c.fetchone()[0]}")
conn.close()
