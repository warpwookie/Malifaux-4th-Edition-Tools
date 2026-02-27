"""Calibration test: compare pdf_text_extractor output against known DB values."""
import sys
sys.path.insert(0, '.')
from scripts.pdf_text_extractor import extract_stat_card_text

cards = [
    ('source_pdfs/Guild/Guard/M4E_Stat_Guard_Dashel_Barker_Butcher.pdf', 'Guild'),
    ('source_pdfs/Guild/Guard/M4E_Stat_Guard_Rifleman_A.pdf', 'Guild'),
    ('source_pdfs/Bayou/Sooey/M4E_Stat_Sooey_War_Pig_A.pdf', 'Bayou'),
    ('source_pdfs/Guild/Guard/M4E_Stat_Guard_Disease_Containment_Unit.pdf', 'Guild'),
    ('source_pdfs/Guild/Guard/M4E_Stat_Guard_Taggart_Queeg.pdf', 'Guild'),
]

expected = {
    'DASHEL BARKER': {
        'health': 14, 'cost': '-',
        'chars': ['Master', 'Living'], 'kw': ['Guard'],
        'df': 6, 'sp': 6, 'wp': 6, 'sz': 2,
        'title': 'BUTCHER',
        'abilities': ['Frenzied Charge', 'Grip of the Guild', 'Threatening Demeanor'],
        'attacks': [('Butcher\u2019s Cleaver', 'melee'), ('Down the Wrong Path', 'magic')],
        'tactical': ['Second Slice'],
    },
    'RIFLEMAN': {
        'health': 7, 'cost': '5',
        'chars': ['Minion (3)', 'Living'], 'kw': ['Guard'],
        'df': 5, 'sp': 6, 'wp': 5, 'sz': 2,
        'title': None,
        'abilities': ['Advanced Sights', 'Sniper', 'Stand and Fire'],
        'attacks': [('Clockwork Rifle', 'missile'), ('Incapacitating Shot', 'missile')],
        'tactical': ['To the Rooftops'],
    },
    'WAR PIG': {
        'health': 12, 'cost': '9',
        'chars': ['Minion (2)', 'Beast'], 'kw': ['Sooey'],
        'df': 5, 'sp': 6, 'wp': 5, 'sz': 3,
        'title': None,
        'abilities': ['Chow Time', 'Frenzied Charge', 'Thick Fat'],
        'attacks': [('Huge Tusks', 'melee')],
        'tactical': ['Rooting Around'],
    },
    'DISEASE CONTAINMENT UNIT': {
        'health': 9, 'cost': '-',
        'chars': ['Totem', 'Unique', 'Living'], 'kw': ['Guard'],
        'df': 5, 'sp': 6, 'wp': 5, 'sz': 2,
        'title': None,
        'abilities': ['Armor', 'Containment Suit'],
        'attacks': [('Hidden Axe', 'melee'), ('Flamethrower', 'missile')],
        'tactical': ['Rapid Response', 'Resupply'],
    },
    'TAGGART QUEEG': {
        'health': 11, 'cost': '8',
        'chars': ['Henchman', 'Unique', 'Living'], 'kw': ['Guard'],
        'df': 5, 'sp': 5, 'wp': 6, 'sz': 2,
        'title': None,
        'abilities': ['Prison Superintendent', 'Taskmaster', 'Threatening Demeanor'],
        'attacks': [('Bleeder Lash', 'melee'), ('Peacebringer', 'missile')],
        'tactical': ['Camaraderie', 'Sabotage Their Plans'],
    },
}

all_ok = True
for pdf_path, faction in cards:
    r = extract_stat_card_text(pdf_path, faction=faction)
    f = r['front']
    b = r['back']
    name = f['name']

    if name not in expected:
        print(f"FAIL | Name '{name}' not in expected (wrong extraction?)")
        all_ok = False
        continue

    exp = expected[name]
    issues = []

    # Front checks
    if f['health'] != exp['health']:
        issues.append(f"health: got {f['health']}, exp {exp['health']}")
    if f['cost'] != exp['cost']:
        issues.append(f"cost: got {f['cost']}, exp {exp['cost']}")
    if f['characteristics'] != exp['chars']:
        issues.append(f"chars: got {f['characteristics']}, exp {exp['chars']}")
    if f['keywords'] != exp['kw']:
        issues.append(f"keywords: got {f['keywords']}, exp {exp['kw']}")
    if f.get('title') != exp['title']:
        issues.append(f"title: got {f.get('title')}, exp {exp['title']}")

    # Stats
    for stat in ['df', 'sp', 'wp', 'sz']:
        got = f['stats'].get(stat)
        if got != exp[stat]:
            issues.append(f"{stat}: got {got}, exp {exp[stat]}")

    # Abilities
    got_abilities = [a['name'] for a in f.get('abilities', [])]
    if got_abilities != exp['abilities']:
        issues.append(f"abilities: got {got_abilities}, exp {exp['abilities']}")

    # Back checks
    if not b['name']:
        issues.append("back name EMPTY")

    # Attack actions
    got_attacks = [(a['name'], a['action_type']) for a in b['attack_actions']]
    if got_attacks != exp['attacks']:
        issues.append(f"attacks: got {got_attacks}, exp {exp['attacks']}")

    # Tactical actions
    got_tactical = [a['name'] for a in b['tactical_actions']]
    if got_tactical != exp['tactical']:
        issues.append(f"tactical: got {got_tactical}, exp {exp['tactical']}")

    # Check triggers have names (no empty names)
    for a in b['attack_actions'] + b['tactical_actions']:
        for t in a['triggers']:
            if not t['name']:
                issues.append(f"empty trigger name on {a['name']}: suit={t['suit']}")

    status = 'PASS' if not issues else 'FAIL'
    if issues:
        all_ok = False
    print(f"\n{status} | {name}")
    print(f"  health={f['health']} cost={f['cost']} title={f.get('title')}")
    print(f"  chars={f['characteristics']}")
    print(f"  kw={f['keywords']}")
    print(f"  abilities={got_abilities}")
    print(f"  back_name={b['name']} attacks={len(b['attack_actions'])} tactical={len(b['tactical_actions'])}")
    for a in b['attack_actions'] + b['tactical_actions']:
        trigs = [(t['suit'], t['name']) for t in a['triggers']]
        cat = 'atk' if a.get('action_type') else 'tac'
        print(f"    {cat}: {a['name']} trigs={trigs}")
    if issues:
        for iss in issues:
            print(f"  ** {iss}")

print(f"\n{'='*60}")
print("ALL PASSED" if all_ok else "SOME FAILURES — see ** lines above")
