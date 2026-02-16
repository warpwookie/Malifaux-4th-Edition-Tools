"""
reextract_targeted.py — Targeted API re-extraction for missing fields.

1. Station extraction: Send card front, ask ONLY for station
2. Trigger suit extraction: Send card back, ask ONLY for trigger suits

Uses minimal prompts for speed and cost efficiency.

Usage:
    python reextract_targeted.py stations              # Preview station extraction
    python reextract_targeted.py stations --apply       # Extract + update stations
    python reextract_targeted.py triggers               # Preview trigger extraction
    python reextract_targeted.py triggers --apply       # Extract + update triggers
    python reextract_targeted.py all --apply            # Both
"""
import base64
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from datetime import datetime

DRY_RUN = "--apply" not in sys.argv
DB_PATH = "db/m4e.db"

try:
    import anthropic
except ImportError:
    print("ERROR: pip install anthropic")
    sys.exit(1)

MODEL = "claude-sonnet-4-5-20250929"

# ============================================================
# PROMPTS — minimal, focused questions
# ============================================================

STATION_PROMPT = """Look at this Malifaux 4th Edition stat card front. 
What is this model's STATION? The station appears near the top of the card, typically after the model name/title line.

Valid stations: Master, Henchman, Enforcer, Minion, Totem, Peon

Respond with ONLY a JSON object:
{"station": "Henchman"}
"""

TRIGGER_SUIT_PROMPT = """Look at this Malifaux 4th Edition stat card back. I need the SUIT ICONS for specific triggers.

Suits are shown as small icons: Ram (diamond shape), Crow (bird/skull), Mask (mask shape), Tome (book shape).
Encode as: (r) = Ram, (c) = Crow, (m) = Mask, (t) = Tome
Multiple suits are concatenated: e.g., (r)(c) means Ram and Crow

I need suits for these specific triggers:
{trigger_list}

Respond with ONLY a JSON object mapping trigger names to their suit:
{{"Trigger Name": "(r)", "Other Trigger": "(m)(c)"}}
"""


def image_to_base64(path):
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    suffix = Path(path).suffix.lower()
    media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(suffix, "image/png")
    return data, media


def call_api(client, image_path, prompt, retries=2):
    img_data, media_type = image_to_base64(image_path)
    for attempt in range(retries + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=512,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_data}},
                        {"type": "text", "text": prompt}
                    ]
                }]
            )
            text = response.content[0].text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            return json.loads(text.strip())
        except (json.JSONDecodeError, Exception) as e:
            if attempt < retries:
                time.sleep(1)
            else:
                return {"error": str(e)}


def find_card_image(source_pdf, side="front"):
    """Find extracted image for a source PDF."""
    pdf_path = Path(source_pdf)
    work_dir = Path("pipeline_work") / pdf_path.stem
    img = work_dir / f"{pdf_path.stem}_{side}.png"
    if img.exists():
        return str(img)
    
    # Try extracting
    if pdf_path.exists():
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            sys.path.insert(0, str(Path("scripts")))
            from pdf_splitter import extract_card_images
            images = extract_card_images(str(pdf_path), str(work_dir))
            if side == "front" and images:
                return images[0]["image_path"]
            elif side == "back" and len(images) > 1:
                return images[1]["image_path"]
        except Exception as e:
            pass
    return None


def extract_stations(conn, client):
    """Re-extract stations for models with NULL station."""
    c = conn.cursor()
    section = "STATION EXTRACTION"
    
    c.execute("""SELECT m.id, m.name, m.title, m.source_pdf, m.cost
                 FROM models m WHERE m.station IS NULL
                 ORDER BY m.id""")
    models = c.fetchall()
    
    print(f"\n{'=' * 60}")
    print(f"{section}: {len(models)} models")
    print(f"{'=' * 60}")
    
    if not models:
        print("  No models need station extraction")
        return
    
    if DRY_RUN:
        for mid, name, title, src, cost in models[:20]:
            print(f"  id={mid} {name} ({title}) cost={cost}")
        if len(models) > 20:
            print(f"  ... and {len(models) - 20} more")
        print(f"\n  Would extract {len(models)} stations. Use --apply.")
        return
    
    # Group by source PDF to avoid re-extracting same card
    # (multiple models can come from same PDF variant)
    results = {"inserted": 0, "errors": 0, "skipped": 0}
    
    for i, (mid, name, title, source_pdf, cost) in enumerate(models):
        print(f"[{i+1}/{len(models)}] {name} ({title})...", end=" ", flush=True)
        
        if not source_pdf:
            print("NO SOURCE PDF")
            results["skipped"] += 1
            continue
        
        img = find_card_image(source_pdf, "front")
        if not img:
            print("NO IMAGE")
            results["skipped"] += 1
            continue
        
        data = call_api(client, img, STATION_PROMPT)
        
        if "error" in data:
            print(f"ERROR: {data['error']}")
            results["errors"] += 1
            continue
        
        station = data.get("station")
        if station and station in ("Master", "Henchman", "Enforcer", "Minion", "Totem", "Peon"):
            c.execute("UPDATE models SET station=? WHERE id=?", (station, mid))
            print(f"-> {station}")
            results["inserted"] += 1
        else:
            print(f"INVALID: {data}")
            results["errors"] += 1
        
        if i < len(models) - 1:
            time.sleep(0.8)
    
    conn.commit()
    print(f"\nStations: {results['inserted']} set, {results['errors']} errors, {results['skipped']} skipped")


def extract_trigger_suits(conn, client):
    """Re-extract suits for triggers with NULL/empty suit."""
    c = conn.cursor()
    section = "TRIGGER SUIT EXTRACTION"
    
    # Group triggers by model (send one image per model, ask about all its missing triggers)
    c.execute("""SELECT t.id, t.name, a.name as action_name, m.id as model_id, m.name as model_name, 
                        m.title, m.source_pdf
                 FROM triggers t
                 JOIN actions a ON t.action_id = a.id
                 JOIN models m ON a.model_id = m.id
                 WHERE t.suit IS NULL OR t.suit = ''
                 ORDER BY m.id, a.name, t.name""")
    missing = c.fetchall()
    
    print(f"\n{'=' * 60}")
    print(f"{section}: {len(missing)} triggers")
    print(f"{'=' * 60}")
    
    if not missing:
        print("  No triggers need suit extraction")
        return
    
    # Group by model
    by_model = {}
    for tid, tname, aname, mid, mname, mtitle, src in missing:
        if mid not in by_model:
            by_model[mid] = {
                "name": mname, "title": mtitle, "source_pdf": src,
                "triggers": []
            }
        by_model[mid]["triggers"].append({
            "trigger_id": tid, "trigger_name": tname, "action_name": aname
        })
    
    print(f"  Across {len(by_model)} models")
    
    if DRY_RUN:
        for mid, info in list(by_model.items())[:10]:
            trigs = ", ".join(t["trigger_name"] for t in info["triggers"])
            print(f"  {info['name']} ({info['title']}): {trigs}")
        if len(by_model) > 10:
            print(f"  ... and {len(by_model) - 10} more models")
        print(f"\n  Would extract suits for {len(missing)} triggers. Use --apply.")
        return
    
    results = {"updated": 0, "errors": 0, "skipped": 0}
    
    for i, (mid, info) in enumerate(by_model.items()):
        mname = info["name"]
        mtitle = info["title"]
        trigs = info["triggers"]
        
        print(f"\n[{i+1}/{len(by_model)}] {mname} ({mtitle}) — {len(trigs)} triggers")
        
        if not info["source_pdf"]:
            print("  NO SOURCE PDF")
            results["skipped"] += len(trigs)
            continue
        
        img = find_card_image(info["source_pdf"], "back")
        if not img:
            print("  NO BACK IMAGE")
            results["skipped"] += len(trigs)
            continue
        
        # Build trigger list for prompt
        trigger_list = "\n".join(
            f"- \"{t['trigger_name']}\" (on action \"{t['action_name']}\")" 
            for t in trigs
        )
        prompt = TRIGGER_SUIT_PROMPT.replace("{trigger_list}", trigger_list)
        
        data = call_api(client, img, prompt)
        
        if "error" in data:
            print(f"  ERROR: {data['error']}")
            results["errors"] += len(trigs)
            continue
        
        # Match results to trigger IDs
        for trig in trigs:
            suit = data.get(trig["trigger_name"])
            if suit and isinstance(suit, str) and any(s in suit for s in ["(r)", "(c)", "(m)", "(t)"]):
                c.execute("UPDATE triggers SET suit=? WHERE id=?", (suit, trig["trigger_id"]))
                print(f"  {trig['trigger_name']}: {suit}")
                results["updated"] += 1
            else:
                # Try case-insensitive match
                matched = False
                for key, val in data.items():
                    if key.lower() == trig["trigger_name"].lower():
                        if val and isinstance(val, str) and any(s in val for s in ["(r)", "(c)", "(m)", "(t)"]):
                            c.execute("UPDATE triggers SET suit=? WHERE id=?", (val, trig["trigger_id"]))
                            print(f"  {trig['trigger_name']}: {val} (case-matched)")
                            results["updated"] += 1
                            matched = True
                            break
                if not matched:
                    print(f"  {trig['trigger_name']}: NOT FOUND in response")
                    results["errors"] += 1
        
        if i < len(by_model) - 1:
            time.sleep(0.8)
    
    conn.commit()
    print(f"\nTrigger suits: {results['updated']} updated, {results['errors']} errors, {results['skipped']} skipped")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("stations", "triggers", "all"):
        print("Usage: python reextract_targeted.py [stations|triggers|all] [--apply]")
        sys.exit(1)
    
    mode = sys.argv[1]
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    
    client = None
    if not DRY_RUN:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("ERROR: Set ANTHROPIC_API_KEY")
            sys.exit(1)
        client = anthropic.Anthropic(api_key=api_key)
    
    if mode in ("stations", "all"):
        extract_stations(conn, client)
    
    if mode in ("triggers", "all"):
        extract_trigger_suits(conn, client)
    
    # Final count
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM models WHERE station IS NULL")
    null_stations = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM triggers WHERE suit IS NULL OR suit=''")
    null_suits = c.fetchone()[0]
    print(f"\nRemaining: {null_stations} null stations, {null_suits} null trigger suits")
    
    conn.close()


if __name__ == "__main__":
    main()
