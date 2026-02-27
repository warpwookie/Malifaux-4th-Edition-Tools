"""Calibration script: dump all text spans from a stat card PDF."""
import fitz
import sys

pdf_path = sys.argv[1] if len(sys.argv) > 1 else 'source_pdfs/Guild/Guard/M4E_Stat_Guard_Dashel_Barker_Butcher.pdf'
doc = fitz.open(pdf_path)
print(f"Pages: {len(doc)}")
print(f"Page 0 size: {doc[0].rect}")
if len(doc) > 1:
    print(f"Page 1 size: {doc[1].rect}")

for page_idx in range(len(doc)):
    page_label = "FRONT" if page_idx == 0 else "BACK"
    print(f"\n{'='*80}")
    print(f"PAGE {page_idx} ({page_label})")
    print(f"{'='*80}")
    page = doc[page_idx]
    data = page.get_text("dict")
    for block in data["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                font = span["font"]
                size = round(span["size"], 1)
                bbox = [round(x, 1) for x in span["bbox"]]
                text = span["text"]
                # Show char codes for symbol font
                if "Symbol" in font or "M4E" in font:
                    codes = [ord(c) for c in text]
                    print(f"{page_label} | font={font:30s} size={size:5.1f} bbox={bbox} codes={codes} text={repr(text)}")
                else:
                    text_display = text.strip()
                    if text_display:
                        print(f"{page_label} | font={font:30s} size={size:5.1f} bbox={bbox} text={repr(text_display)}")
doc.close()
