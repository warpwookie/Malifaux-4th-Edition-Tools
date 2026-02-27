import json

# Known values to validate
checks = {
    'Clockwork Trap': ('Arcanists', None),
    'Zombie Chihuahua': ('Resurrectionists', None),
    'Mindless Zombie': ('Resurrectionists', None),
    'Charles Hoffman': ('Guild', 'Inventor'),
    'Banasuva': ('Arcanists', None),
    'Aunty Mel': ('Bayou', None),
    'Abyssal Anchor': ('Neverborn', None),
    'Abomination': ('Outcasts', None),
    'Ashigaru': ('Resurrectionists', None),
}

# Load all models
with open('Model Data Json/m4e_models_all.json', 'r', encoding='utf-8') as f:
    models = json.load(f)

for name, (faction, title) in checks.items():
    matches = [m for m in models if m['name'] == name and m['faction'] == faction]
    if title:
        matches = [m for m in matches if m.get('title') == title]
    if matches:
        m = matches[0]
        print(f"{name} ({faction}): health={m['health']}, shields={m['shields']}, "
              f"soulstone_on_death={m['infuses_soulstone_on_death']}")
    else:
        print(f"{name} ({faction}): NOT FOUND")
