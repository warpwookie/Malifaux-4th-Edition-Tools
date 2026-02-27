"""Check for health/soulstone data in PDF text and graphics layers."""
import fitz
import sys

pdf_path = sys.argv[1] if len(sys.argv) > 1 else 'source_pdfs/Guild/Guard/M4E_Stat_Guard_Rifleman_A.pdf'
doc = fitz.open(pdf_path)
page = doc[0]  # front page

# Check rawdict for any hidden text
print("=== RAWDICT: all spans including hidden ===")
data = page.get_text("rawdict")
for block in data["blocks"]:
    if block["type"] != 0:
        continue
    for line in block["lines"]:
        for span in line["spans"]:
            # rawdict uses "chars" instead of "text"
            chars = span.get("chars", [])
            text = "".join(c["c"] for c in chars)
            font = span["font"]
            color = span.get("color", 0)
            flags = span.get("flags", 0)
            size = round(span["size"], 1)
            bbox = [round(x, 1) for x in span["bbox"]]
            if text.strip():
                print(f"font={font:30s} size={size:5.1f} color={color:#010x} flags={flags:3d} bbox={bbox} text={repr(text.strip())}")

# Check for drawings/paths that might be health pips
print("\n=== DRAWINGS (vector paths) ===")
drawings = page.get_drawings()
print(f"Total drawings: {len(drawings)}")
# Look for small circles that could be health pips
circles = []
for d in drawings:
    for item in d["items"]:
        if item[0] == "c":  # curve
            pass
        elif item[0] == "re":  # rectangle
            rect = item[1]
            w = rect.width
            h = rect.height
            if 3 < w < 12 and 3 < h < 12:  # Small rectangles/squares could be pips
                circles.append({"rect": rect, "fill": d.get("fill"), "color": d.get("color")})
    # Also check if it looks like a circle/pip
    rect = fitz.Rect(d["rect"])
    w = rect.width
    h = rect.height
    if 3 < w < 12 and 3 < h < 12 and abs(w - h) < 2:
        circles.append({"rect": rect, "fill": d.get("fill"), "color": d.get("color"), "items": len(d["items"])})

print(f"Small square-ish drawings (potential pips): {len(circles)}")
for c in circles[:20]:
    print(f"  rect={c['rect']} fill={c.get('fill')} color={c.get('color')}")

# Also check for annotations
print(f"\n=== ANNOTATIONS ===")
for annot in page.annots():
    print(f"  {annot}")

doc.close()
