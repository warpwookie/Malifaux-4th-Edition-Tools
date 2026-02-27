import fitz

pdfs = {
    'Rifleman (health should be ~7)': 'source_pdfs/Guild/Guard/M4E_Stat_Guard_Rifleman_A.pdf',
    'Dashel (health should be ~10-12)': 'source_pdfs/Guild/Guard/M4E_Stat_Guard_Dashel_Barker_Butcher.pdf',
    'War Pig (health should be ~8-10)': 'source_pdfs/Bayou/Sooey/M4E_Stat_Sooey_War_Pig_A.pdf',
}

for label, pdf_path in pdfs.items():
    doc = fitz.open(pdf_path)
    page = doc[0]
    drawings = page.get_drawings()

    # Group drawings by Y-position regions
    regions = {}
    for d in drawings:
        rect = fitz.Rect(d['rect'])
        cy = (rect.y0 + rect.y1) / 2
        # Group into 10pt bands
        band = int(cy / 10) * 10
        regions.setdefault(band, []).append(d)

    print(f"\n{'='*60}")
    print(f"{label} ({pdf_path})")
    print(f"Total drawings: {len(drawings)}")
    for band in sorted(regions.keys()):
        items = regions[band]
        print(f"  Y-band {band}-{band+10}: {len(items)} drawings")
        # Show details for first few
        for d in items[:3]:
            rect = fitz.Rect(d['rect'])
            fill = d.get('fill')
            n_items = len(d['items'])
            print(f"    rect=({rect.x0:.1f},{rect.y0:.1f},{rect.x1:.1f},{rect.y1:.1f}) fill={fill} items={n_items}")

    doc.close()
