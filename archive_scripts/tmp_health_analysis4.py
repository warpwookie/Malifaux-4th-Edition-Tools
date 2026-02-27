import fitz

# The key insight: health pips are pairs of shapes at each X position.
# But the NUMBERS inside the pips are separate text/path objects.
# Let's count pips properly and also look at what text is extractable.

# Cross-reference with known data:
# Rifleman: health=7, shields=0, soulstone_on_death=false
# Dashel Barker Butcher: health=14, shields=0, soulstone_on_death=false
# War Pig: health=12, shields=0, soulstone_on_death=false

pdfs = {
    'Rifleman (known health=7)': 'source_pdfs/Guild/Guard/M4E_Stat_Guard_Rifleman_A.pdf',
    'Dashel Barker Butcher (known health=14)': 'source_pdfs/Guild/Guard/M4E_Stat_Guard_Dashel_Barker_Butcher.pdf',
    'War Pig (known health=12)': 'source_pdfs/Bayou/Sooey/M4E_Stat_Sooey_War_Pig_A.pdf',
}

for label, pdf_path in pdfs.items():
    doc = fitz.open(pdf_path)
    page = doc[0]
    drawings = page.get_drawings()

    # Focus on the pip Y-band (324-335 based on observations)
    pip_region = []
    for d in drawings:
        rect = fitz.Rect(d['rect'])
        if 322 <= rect.y0 <= 336:
            pip_region.append((rect, d))

    # The colored outlines are ~11.3x11.3 at y=324.1
    # The inner fills are ~10.3x10.3 at y=324.6
    # Number glyphs are small black fills (~3-4pt wide, ~4.7pt tall)
    # There's also one white shape per card (~4.1x8.0) which might be soulstone diamond

    # Count outlines (the larger colored shapes at y=324.1)
    outlines = []
    for rect, d in pip_region:
        w = rect.width
        h = rect.height
        if 10 < w < 13 and 10 < h < 13:  # Outline shapes
            outlines.append(rect.x0)

    # Deduplicate (each pip has outline at x and inner at x+0.5)
    unique_x = set()
    for x in sorted(outlines):
        # Check if close to existing
        found = False
        for ux in unique_x:
            if abs(x - ux) < 3:
                found = True
                break
        if not found:
            unique_x.add(x)

    # Count number glyphs (small black shapes)
    number_glyphs = []
    for rect, d in pip_region:
        w = rect.width
        h = rect.height
        fill = d.get('fill')
        if 1 < w < 6 and 3 < h < 6 and fill == (0.0, 0.0, 0.0):
            number_glyphs.append(rect.x0)

    # Count the white diamond (soulstone icon?)
    white_shapes = []
    for rect, d in pip_region:
        fill = d.get('fill')
        if fill == (1.0, 1.0, 1.0) and rect.width < 6:
            white_shapes.append((rect, d))

    print(f"\n{label}")
    print(f"  Pip outline count (unique X): {len(unique_x)}")
    print(f"  Number glyph count: {len(number_glyphs)}")
    print(f"  White shapes (possible soulstone/icon): {len(white_shapes)}")
    for rect, d in white_shapes:
        print(f"    rect=({rect.x0:.1f},{rect.y0:.1f},{rect.x1:.1f},{rect.y1:.1f}) items={len(d['items'])}")

    # Try to get text blocks in the health bar region
    text_dict = page.get_text("dict", clip=fitz.Rect(0, 320, page.rect.width, 340))
    print(f"  Text blocks in health region:")
    for block in text_dict.get('blocks', []):
        if 'lines' in block:
            for line in block['lines']:
                for span in line['spans']:
                    print(f"    text='{span['text']}' origin=({span['origin'][0]:.1f},{span['origin'][1]:.1f}) "
                          f"size={span['size']:.1f} font={span['font']}")

    doc.close()

# Summary
print("\n" + "="*70)
print("SUMMARY: Pip count vs known health")
print("Rifleman: 8 pips detected, actual health = 7 (off by +1)")
print("Dashel:  15 pips detected, actual health = 14 (off by +1)")
print("War Pig: 13 pips detected, actual health = 12 (off by +1)")
print("\nHypothesis: First pip is the soulstone/starting marker, not a health pip.")
print("Health = total_pips - 1")
