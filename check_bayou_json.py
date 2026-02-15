import json

d = json.load(open("data/all_cards_bayou.json", encoding="utf-8"))

# Check for Ophelia, Ulix, Flying Piglet
for model in d:
    name = model.get("name", "")
    title = model.get("title", "")
    if any(t in name.lower() for t in ["ophelia", "ulix", "flying piglet", "piglet"]):
        print(f"  name='{name}'  title='{title}'")

print(f"\nTotal Bayou models in JSON: {len(d)}")
