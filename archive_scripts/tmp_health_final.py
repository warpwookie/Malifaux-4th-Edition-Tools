import fitz
import json
import os

# Load all models for cross-reference
with open('Model Data Json/m4e_models_all.json', 'r', encoding='utf-8') as f:
    models = json.load(f)

# Find a model with soulstone_on_death=true to test
ss_models = [m for m in models if m['infuses_soulstone_on_death']]
print(f"Models with soulstone_on_death=true: {len(ss_models)}")
for m in ss_models[:5]:
    print(f"  {m['name']} ({m['faction']}): health={m['health']}")

# Find a model with shields > 0
shield_models = [m for m in models if m.get('shields', 0) > 0]
print(f"\nModels with shields > 0: {len(shield_models)}")

# Find a model with health=0 (Marathine)
zero_health = [m for m in models if m['health'] == 0]
print(f"\nModels with health=0: {len(zero_health)}")
for m in zero_health:
    print(f"  {m['name']} ({m['faction']})")


def count_health_from_pdf(pdf_path):
    """Count health pips from PDF drawings."""
    doc = fitz.open(pdf_path)
    page = doc[0]
    drawings = page.get_drawings()

    pip_region = []
    for d in drawings:
        rect = fitz.Rect(d['rect'])
        if 322 <= rect.y0 <= 336:
            pip_region.append((rect, d))

    # Count outlines (10-13pt colored shapes)
    outlines = []
    for rect, d in pip_region:
        w = rect.width
        h = rect.height
        if 10 < w < 13 and 10 < h < 13:
            outlines.append(rect.x0)

    # Deduplicate by X proximity
    unique_x = []
    for x in sorted(outlines):
        if not unique_x or abs(x - unique_x[-1]) > 3:
            unique_x.append(x)

    total_pips = len(unique_x)

    # The first pip is always the "starting position" marker (pip 0)
    # The remaining pips are health
    # But for health=1 models (Clockwork Trap), total_pips=1
    # So: if total_pips == 1 and only one small glyph, health=1
    # For health=0 (Marathine), presumably total_pips=0

    # Count white diamond shapes (soulstone marker)
    white_diamonds = 0
    for rect, d in pip_region:
        fill = d.get('fill')
        if fill == (1.0, 1.0, 1.0) and rect.width < 6 and rect.height > 6:
            white_diamonds += 1

    # Check if first pip has different fill pattern (all colored = soulstone)
    first_pip_is_soulstone = False
    if unique_x:
        first_x = unique_x[0]
        first_shapes = [(rect, d) for rect, d in pip_region
                        if 10 < rect.width < 13 and abs(rect.x0 - first_x) < 3]
        # Check inner shape
        first_inners = [(rect, d) for rect, d in pip_region
                        if 9 < rect.width < 12 and abs(rect.x0 - first_x) < 4]
        inner_fills = [d.get('fill') for rect, d in first_inners]
        # If no white inner, first pip is "special" (soulstone)
        first_pip_is_soulstone = all(f != (1.0, 1.0, 1.0) for f in inner_fills)

    doc.close()

    return {
        'total_pips': total_pips,
        'health': max(0, total_pips - 1) if total_pips > 1 else total_pips,
        'white_diamonds': white_diamonds,
        'first_pip_special': first_pip_is_soulstone,
    }


# Validation comparison table
print("\n\n" + "="*70)
print("VALIDATION: PDF pip count vs JSON health value")
print("="*70)

# Compile results
validation_data = [
    ('Rifleman', 'Guild', 'Guard', 'M4E_Stat_Guard_Rifleman_A.pdf'),
    ('Dashel Barker Butcher', 'Guild', 'Guard', 'M4E_Stat_Guard_Dashel_Barker_Butcher.pdf'),
    ('War Pig', 'Bayou', 'Sooey', 'M4E_Stat_Sooey_War_Pig_A.pdf'),
    ('Clockwork Trap', 'Arcanists', 'Frontier', 'M4E_Stat_Frontier_Clockwork_Trap_A.pdf'),
    ('Zombie Chihuahua', 'Resurrectionists', 'Experimental', 'M4E_Stat_Experimental_Zombie_Chihuahua.pdf'),
    ('Mindless Zombie', 'Resurrectionists', 'Versatile - Resurrectionists', 'M4E_Stat_Res-Versatile_Mindless_Zombie_A.pdf'),
    ('Dashel Barker Old Guard', 'Guild', 'Guard', 'M4E_Stat_Guard_Dashel_Barker_The_Old_Guard.pdf'),
    ('Charles Hoffman', 'Guild', 'Augmented', 'M4E_Stat_Augmented_Charles_Hoffman_Inventor.pdf'),
    ('Banasuva', 'Arcanists', 'Academic', 'M4E_Stat_Academic_Banasuva.pdf'),
    ('Aunty Mel', 'Bayou', 'Angler', 'M4E_Stat_Angler_Aunty_Mel.pdf'),
    ('Abyssal Anchor', 'Neverborn', 'Banished', 'M4E_Stat_Banished_Abyssal_Anchor.pdf'),
    ('Abomination', 'Outcasts', 'Amalgam', 'M4E_Stat_Amalgam_Abomination_A.pdf'),
    ('Ashigaru', 'Resurrectionists', 'Ancestor', 'M4E_Stat_Ancestor_Ashigaru_A.pdf'),
]

known_health = {
    'Rifleman': 7,
    'Dashel Barker Butcher': 14,
    'War Pig': 12,
    'Clockwork Trap': 1,
    'Zombie Chihuahua': 7,
    'Mindless Zombie': 1,
    'Dashel Barker Old Guard': 14,
    'Charles Hoffman': 12,
    'Banasuva': 9,
    'Aunty Mel': 11,
    'Abyssal Anchor': 7,
    'Abomination': 5,
    'Ashigaru': 5,
}

print(f"\n{'Model':<30} {'Known':>5} {'Pips':>5} {'Est':>5} {'Match':>6} {'1stPip':>7} {'Diamond':>8}")
print("-" * 76)

for name, faction, keyword, filename in validation_data:
    pdf_path = os.path.join('source_pdfs', faction, keyword, filename)
    if not os.path.exists(pdf_path):
        print(f"{name:<30} {'N/A':>5} PDF not found")
        continue

    result = count_health_from_pdf(pdf_path)
    kh = known_health.get(name, '?')

    # For health=1 models: total_pips=1, which is the health itself (no starting marker)
    # For health>1: total_pips = health + 1 (one starting marker)
    if result['total_pips'] <= 1:
        estimated = result['total_pips']
    else:
        estimated = result['total_pips'] - 1

    match = "YES" if estimated == kh else "NO"
    print(f"{name:<30} {kh:>5} {result['total_pips']:>5} {estimated:>5} {match:>6} "
          f"{'Y' if result['first_pip_special'] else 'N':>7} {result['white_diamonds']:>8}")
