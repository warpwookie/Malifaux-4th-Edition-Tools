"""Check all FAILED cards across factions. Use --crew for crew cards, --stat for stat cards, or no flag for all."""
import os, json, sys

show_stat = "--stat" in sys.argv or (not "--crew" in sys.argv and not "--stat" in sys.argv)
show_crew = "--crew" in sys.argv or (not "--crew" in sys.argv and not "--stat" in sys.argv)

base = "pipeline_work"
count = 0
for entry in sorted(os.listdir(base)):
    path = os.path.join(base, entry)
    if not os.path.isdir(path):
        continue
    for f in sorted(os.listdir(path)):
        if "FAILED" not in f:
            continue
        is_crew = "Crew" in f
        is_stat = "Stat" in f
        if is_crew and not show_crew:
            continue
        if is_stat and not show_stat:
            continue
        if not is_crew and not is_stat:
            continue

        d = json.load(open(os.path.join(path, f), encoding="utf-8"))
        v = d.get("validation", {})
        name = v.get("card_name", "?")
        print(f"[{entry}] {name}  ({f})")
        for h in v.get("hard_violations", []):
            print(f"  HARD: {h}")
        for s in v.get("soft_flags", []):
            print(f"  SOFT: {s}")
        print()
        count += 1

print(f"Total failures: {count}")
