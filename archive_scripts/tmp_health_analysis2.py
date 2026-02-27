import fitz

pdfs = {
    'Rifleman (health=7)': 'source_pdfs/Guild/Guard/M4E_Stat_Guard_Rifleman_A.pdf',
    'Dashel (health=10-12)': 'source_pdfs/Guild/Guard/M4E_Stat_Guard_Dashel_Barker_Butcher.pdf',
    'War Pig (health=8-10)': 'source_pdfs/Bayou/Sooey/M4E_Stat_Sooey_War_Pig_A.pdf',
}

for label, pdf_path in pdfs.items():
    doc = fitz.open(pdf_path)
    page = doc[0]

    print(f"\n{'='*70}")
    print(f"{label}")
    print(f"  Page size: {page.rect.width:.1f} x {page.rect.height:.1f}")

    # Focus on Y-band 320-330 where health pips seem to be
    drawings = page.get_drawings()
    pip_drawings = [d for d in drawings if 320 <= (fitz.Rect(d['rect']).y0 + fitz.Rect(d['rect']).y1) / 2 <= 340]

    print(f"\n  Drawings in Y-band 320-340: {len(pip_drawings)}")

    # Look for repeated small shapes (pips are usually small circles/squares)
    small_shapes = []
    for d in pip_drawings:
        rect = fitz.Rect(d['rect'])
        w = rect.width
        h = rect.height
        fill = d.get('fill')
        if 5 < w < 15 and 5 < h < 15:  # Small square-ish shapes
            small_shapes.append({
                'x': rect.x0,
                'y': rect.y0,
                'w': w,
                'h': h,
                'fill': fill,
                'items': len(d['items'])
            })

    print(f"  Small shapes (5-15pt) in pip area: {len(small_shapes)}")
    for s in sorted(small_shapes, key=lambda x: x['x']):
        fill_desc = "white" if s['fill'] == (1.0, 1.0, 1.0) else f"color={s['fill']}"
        print(f"    x={s['x']:.1f} y={s['y']:.1f} size={s['w']:.1f}x{s['h']:.1f} {fill_desc} items={s['items']}")

    # Count "filled" pips (colored, non-white, non-black backgrounds)
    colored_pips = [s for s in small_shapes if s['fill'] and s['fill'] != (1.0, 1.0, 1.0) and s['fill'] != (0.0, 0.0, 0.0)]
    white_pips = [s for s in small_shapes if s['fill'] == (1.0, 1.0, 1.0)]

    print(f"\n  Colored (filled) pip-like shapes: {len(colored_pips)}")
    print(f"  White (empty/outline) pip-like shapes: {len(white_pips)}")

    # Also extract text to see if health is mentioned anywhere
    print(f"\n  --- Text extraction ---")
    text = page.get_text()
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    for line in lines:
        print(f"    '{line}'")

    # Try text in specific regions
    print(f"\n  --- Text near pip area (Y=310-345) ---")
    clip = fitz.Rect(0, 310, page.rect.width, 345)
    text_pip = page.get_text(clip=clip)
    if text_pip.strip():
        print(f"    '{text_pip.strip()}'")
    else:
        print(f"    (no text found)")

    doc.close()
