"""Diagnostic script: investigate remaining bugs on Dashel Barker."""
import sys
sys.path.insert(0, '.')
from scripts.pdf_text_extractor import (
    _get_page_spans, _group_into_lines, _classify_action_line,
    _map_symbol_text, FONT_SYMBOL, FONT_ABILITY_NAME, FONT_BODY,
    FONT_BOLD, FONT_ITALIC, FONT_TRIGGER, FONT_NAME_LARGE, FONT_NAME_ITALIC,
    ABILITIES_Y_START, DEFENSIVE_ICON_MAP, _get_symbol_codes
)
import fitz

pdf_path = 'source_pdfs/Guild/Guard/M4E_Stat_Guard_Dashel_Barker_Butcher.pdf'
doc = fitz.open(pdf_path)

# === BUG 2: Back page name ===
print("=" * 70)
print("BUG 2: Back page name — ALL spans with Y < 35 on page 1 (back)")
print("=" * 70)
back_spans = _get_page_spans(doc[1])
for s in back_spans:
    if s["y0"] < 35:
        print(f"  font={s['font']:30s} size={s['size']:5.1f} "
              f"[{s['x0']:6.1f},{s['y0']:6.1f}]-[{s['x1']:6.1f},{s['y1']:6.1f}] "
              f"text={repr(s['text'])}")

# === Also check: are there Astoria-Bold spans ANYWHERE on back page? ===
print("\n--- All Astoria-Bold spans on back page ---")
for s in back_spans:
    if s["font"] == FONT_NAME_LARGE:
        print(f"  size={s['size']:5.1f} [{s['x0']:6.1f},{s['y0']:6.1f}]-[{s['x1']:6.1f},{s['y1']:6.1f}] text={repr(s['text'])}")

# === BUG 3: Ability splitting — show line-by-line with classifications ===
print("\n" + "=" * 70)
print("BUG 3: Front page ability lines (Y > 225)")
print("=" * 70)
front_spans = _get_page_spans(doc[0])
ability_spans = [s for s in front_spans if s["y0"] > ABILITIES_Y_START]
lines = _group_into_lines(ability_spans, tolerance=2.0)

for i, line_spans in enumerate(lines):
    first = line_spans[0]
    # Show key info about each line
    fonts = [s["font"].split("-")[-1] for s in line_spans]
    texts = []
    for s in line_spans:
        if s["font"] == FONT_SYMBOL:
            mapped = _map_symbol_text(s["text"], s["font"])
            codes = _get_symbol_codes(s)
            texts.append(f"[SYM:{mapped} codes={codes}]")
        else:
            texts.append(s["text"][:30])

    # Check defensive icon
    has_defensive = False
    if first["font"] == FONT_SYMBOL:
        codes = _get_symbol_codes(first)
        has_defensive = any(c in DEFENSIVE_ICON_MAP for c in codes)

    # Check for ExtraBold ending with ":"
    has_name = False
    for s in line_spans:
        if s["font"] == FONT_ABILITY_NAME and s["text"].strip().endswith(":"):
            has_name = True
            break

    print(f"\n  Line {i}: Y={first['y0']:.1f} X={first['x0']:.1f} "
          f"def_icon={has_defensive} has_name={has_name}")
    print(f"    fonts: {fonts}")
    print(f"    texts: {' | '.join(texts)}")

# === BUG 4: Trigger detection on back page ===
print("\n" + "=" * 70)
print("BUG 4: Back page action section lines — classifications")
print("=" * 70)

# Find section headers
header_spans = [s for s in back_spans
                if s["font"] == FONT_ABILITY_NAME
                and 7.5 <= s["size"] <= 10.0]
print("Section headers found:")
for s in header_spans:
    print(f"  size={s['size']:.1f} Y={s['y0']:.1f} text={repr(s['text'])}")

# Get action section spans (Y between first header and base_size area)
action_section_spans = [s for s in back_spans if 50 < s["y0"] < 320]
action_lines = _group_into_lines(action_section_spans, tolerance=2.0)

has_active_trigger = False
for i, line_spans in enumerate(action_lines):
    line_type = _classify_action_line(line_spans, has_active_trigger)

    if line_type == "trigger":
        has_active_trigger = True
    elif line_type in ("action_header", "effect_text"):
        has_active_trigger = False

    first = line_spans[0]
    fonts = [s["font"].split("-")[-1][:8] for s in line_spans]
    text_preview = " ".join(s["text"][:20] for s in line_spans if s["font"] != FONT_SYMBOL)
    sym_text = " ".join(_map_symbol_text(s["text"], s["font"]) for s in line_spans if s["font"] == FONT_SYMBOL)

    print(f"  Line {i:2d}: [{line_type:22s}] Y={first['y0']:6.1f} X={first['x0']:5.1f} "
          f"sym={sym_text:20s} fonts={fonts}")
    print(f"           text: {text_preview[:80]}")

doc.close()
