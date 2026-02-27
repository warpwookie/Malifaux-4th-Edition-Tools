import fitz
import os

# Test on more models for validation
# Dashel Old Guard: health=14, soulstone_on_death=TRUE
# Need to find its PDF

# Let's find more PDFs to test
test_cases = []

# Walk source_pdfs to find a few specific ones
for root, dirs, files in os.walk('source_pdfs'):
    for f in files:
        if f.endswith('.pdf') and 'Stat' in f:
            # Pick a few diverse ones
            lower = f.lower()
            if 'clockwork_trap' in lower or 'guild_steward' in lower or 'zombie' in lower:
                test_cases.append(os.path.join(root, f))

# Also add Dashel Old Guard if available
for root, dirs, files in os.walk('source_pdfs'):
    for f in files:
        if 'Dashel' in f and 'Old_Guard' in f:
            test_cases.append(os.path.join(root, f))

print("Found PDFs:")
for tc in test_cases:
    print(f"  {tc}")


def count_health_pips(pdf_path):
    """Count health pips using the discovered pattern."""
    doc = fitz.open(pdf_path)
    page = doc[0]
    drawings = page.get_drawings()

    # Focus on pip Y-band (y0 between 322-336)
    pip_region = []
    for d in drawings:
        rect = fitz.Rect(d['rect'])
        if 322 <= rect.y0 <= 336:
            pip_region.append((rect, d))

    # Count outline shapes (10-13pt size, colored)
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

    # Count the "first pip" indicator
    # The first pip always has both colored fill shapes (no white inner)
    # Actually, let's check: is the first pip the soulstone marker or just pip #0?

    # Check for the white diamond/soulstone shape
    white_shapes = []
    for rect, d in pip_region:
        fill = d.get('fill')
        if fill == (1.0, 1.0, 1.0) and rect.width < 6:
            white_shapes.append(rect.x0)

    # Number glyphs (the numbers inside pips)
    number_glyphs = 0
    for rect, d in pip_region:
        w = rect.width
        h = rect.height
        fill = d.get('fill')
        if 1 < w < 6 and 3 < h < 6 and fill == (0.0, 0.0, 0.0):
            number_glyphs += 1

    doc.close()

    return {
        'total_pips': total_pips,
        'health_estimate': total_pips - 1,  # subtract starting position
        'number_glyphs': number_glyphs,
        'white_shapes': len(white_shapes),
    }


# Run on all found test cases
for tc in test_cases:
    result = count_health_pips(tc)
    print(f"\n{os.path.basename(tc)}:")
    print(f"  Pips: {result['total_pips']}, Estimated health: {result['health_estimate']}")
    print(f"  Number glyphs: {result['number_glyphs']}, White shapes: {result['white_shapes']}")


# Now test a broader set - pick 1 card from each faction
print("\n\n" + "="*70)
print("BROADER VALIDATION")
print("="*70)

# Find first stat card in each faction folder
factions = ['Guild', 'Arcanists', 'Bayou', 'Neverborn', 'Outcasts', 'Resurrectionists', 'TenThunders', 'ExplorersSociety']
for faction in factions:
    faction_dir = os.path.join('source_pdfs', faction)
    if not os.path.isdir(faction_dir):
        continue
    # Get first keyword subfolder and first stat PDF
    for keyword in sorted(os.listdir(faction_dir)):
        keyword_dir = os.path.join(faction_dir, keyword)
        if not os.path.isdir(keyword_dir):
            continue
        for f in sorted(os.listdir(keyword_dir)):
            if f.startswith('M4E_Stat') and f.endswith('.pdf'):
                pdf_path = os.path.join(keyword_dir, f)
                result = count_health_pips(pdf_path)
                print(f"\n{faction}/{keyword}/{f}:")
                print(f"  Pips: {result['total_pips']}, Health estimate: {result['health_estimate']}")
                print(f"  Number glyphs: {result['number_glyphs']}, White shapes: {result['white_shapes']}")
                break
        break
