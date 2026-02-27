"""Find hidden text elements that might encode health/soulstone/shields."""
import fitz
import sys

pdfs = [
    'source_pdfs/Guild/Guard/M4E_Stat_Guard_Dashel_Barker_Butcher.pdf',
    'source_pdfs/Guild/Guard/M4E_Stat_Guard_Rifleman_A.pdf',
    'source_pdfs/Bayou/Sooey/M4E_Stat_Sooey_War_Pig_A.pdf',
    'source_pdfs/Guild/Guard/M4E_Stat_Guard_Sergeant_A.pdf',
    'source_pdfs/Guild/Guard/M4E_Stat_Guard_Executioner_A.pdf',
]

for pdf_path in pdfs:
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"SKIP {pdf_path}: {e}")
        continue
    page = doc[0]
    # Look for ALL Astoria-Bold text at 7.0pt that might be station/health markers
    data = page.get_text("dict")
    print(f"\n{'='*60}")
    print(f"FILE: {pdf_path}")
    # Gather all unique (font, size, text, y) combos
    all_spans = []
    seen = set()
    for block in data["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                font = span["font"]
                size = round(span["size"], 1)
                bbox = tuple(round(x, 1) for x in span["bbox"])
                text = span["text"]
                key = (font, size, bbox, text)
                if key in seen:
                    continue
                seen.add(key)
                all_spans.append((font, size, bbox, text))

    # Show any Astoria-Bold at 6-8pt range (station/health candidates)
    print("--- Astoria-Bold 6-8pt (potential station/health/title) ---")
    for font, size, bbox, text in all_spans:
        if font == "Astoria-Bold" and 6.0 <= size <= 8.0:
            t = text.strip()
            if t:
                print(f"  size={size} bbox={list(bbox)} text={repr(t)}")

    # Also show any small numbers in unexpected fonts
    print("--- ModestoPoster values (stat values) ---")
    for font, size, bbox, text in all_spans:
        if "Modesto" in font:
            t = text.strip()
            if t:
                print(f"  size={size} bbox={list(bbox)} text={repr(t)}")

    # Check bottom area of front page (Y > 315) for any text
    print("--- Bottom area (Y > 315) ---")
    for font, size, bbox, text in all_spans:
        if bbox[1] > 315:
            t = text.strip()
            if t:
                print(f"  font={font} size={size} bbox={list(bbox)} text={repr(t)}")

    doc.close()
