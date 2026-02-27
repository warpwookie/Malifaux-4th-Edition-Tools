import fitz

# Each pip is a pair of shapes at the same X: one colored outline (~11.3x11.3) and one inner (~10.3x10.3)
# The first pip has BOTH colored (outline + inner), rest have colored outline + white inner
# So: count = number of unique X positions (grouped by ~12.4pt spacing)

pdfs = {
    'Rifleman': ('source_pdfs/Guild/Guard/M4E_Stat_Guard_Rifleman_A.pdf', None),
    'Dashel Barker Butcher': ('source_pdfs/Guild/Guard/M4E_Stat_Guard_Dashel_Barker_Butcher.pdf', None),
    'War Pig': ('source_pdfs/Bayou/Sooey/M4E_Stat_Sooey_War_Pig_A.pdf', None),
}

for label, (pdf_path, _) in pdfs.items():
    doc = fitz.open(pdf_path)
    page = doc[0]
    drawings = page.get_drawings()

    # Filter to pip region
    pip_drawings = []
    for d in drawings:
        rect = fitz.Rect(d['rect'])
        cy = (rect.y0 + rect.y1) / 2
        w = rect.width
        h = rect.height
        if 320 <= cy <= 340 and 5 < w < 15 and 5 < h < 15:
            pip_drawings.append(d)

    # Group by X position (within 3pt tolerance)
    x_groups = {}
    for d in pip_drawings:
        rect = fitz.Rect(d['rect'])
        x = rect.x0
        # Find existing group
        found = False
        for gx in x_groups:
            if abs(x - gx) < 3:
                x_groups[gx].append(d)
                found = True
                break
        if not found:
            x_groups[x] = [d]

    # Each X-group = 1 health pip
    pip_count = len(x_groups)

    # Also check for shield-like shapes or soulstone markers (different shape/color in same region)
    # The first pip that has both colored fills might be soulstone marker
    first_group_x = min(x_groups.keys()) if x_groups else None
    first_all_colored = False
    if first_group_x:
        shapes = x_groups[first_group_x]
        fills = [d.get('fill') for d in shapes]
        white_count = sum(1 for f in fills if f == (1.0, 1.0, 1.0))
        first_all_colored = white_count == 0

    print(f"{label}: {pip_count} pips detected (first pip all-colored: {first_all_colored})")

    # Look for any tiny shapes that might be number text or shield icons nearby
    all_320_340 = [d for d in drawings if 320 <= (fitz.Rect(d['rect']).y0 + fitz.Rect(d['rect']).y1) / 2 <= 340]
    non_pip = [d for d in all_320_340 if d not in pip_drawings]
    print(f"  Non-pip drawings in row: {len(non_pip)}")
    for d in non_pip:
        rect = fitz.Rect(d['rect'])
        fill = d.get('fill')
        print(f"    rect=({rect.x0:.1f},{rect.y0:.1f},{rect.x1:.1f},{rect.y1:.1f}) "
              f"size={rect.width:.1f}x{rect.height:.1f} fill={fill} items={len(d['items'])}")

    doc.close()
