"""Diagnose edge case parsing issues."""
import sys
sys.path.insert(0, '.')
from scripts.pdf_text_extractor import extract_stat_card_text

# Maxine Agassiz
r = extract_stat_card_text(
    "source_pdfs/Explorer's Society/EVS/M4E_Stat_EVS_Maxine_Agassiz_The_Renowned.pdf",
    faction="Explorer's Society")
print("=== MAXINE AGASSIZ ===")
for a in r['back']['attack_actions']:
    print(f"  ATK: {repr(a['name'])} type={a['action_type']} resist={a['resist']} rg={a['range']}")
for a in r['back']['tactical_actions']:
    print(f"  TAC: {repr(a['name'])} rg={a['range']}")

# Asami Tanaka
r2 = extract_stat_card_text(
    "source_pdfs/Ten Thunders/Oni/M4E_Stat_Oni_Asami_Tanaka_Oni_Mother.pdf",
    faction="Ten Thunders")
print("\n=== ASAMI TANAKA ===")
for a in r2['back']['attack_actions']:
    print(f"  ATK: {repr(a['name'])} type={a['action_type']} resist={a['resist']} rg={a['range']}")
for a in r2['back']['tactical_actions']:
    print(f"  TAC: {repr(a['name'])} rg={a['range']}")

# Marathine
r3 = extract_stat_card_text(
    "source_pdfs/Neverborn/Returned/M4E_Stat_Returned_Marathine.pdf",
    faction="Neverborn")
print(f"\n=== MARATHINE ===")
print(f"Health: {r3['front']['health']}")
