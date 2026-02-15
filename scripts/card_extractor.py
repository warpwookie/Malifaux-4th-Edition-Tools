#!/usr/bin/env python3
"""
card_extractor.py â€” Send card images to Claude API for structured data extraction.

Sends front/back images with appropriate prompts and returns parsed JSON.
Supports both stat cards and crew cards.

Usage:
    python card_extractor.py front.png back.png --output card.json
    python card_extractor.py crew_card.png --card-type crew --output crew.json

Requires: ANTHROPIC_API_KEY environment variable
"""
import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic SDK required. Install: pip install anthropic")
    sys.exit(1)


SCRIPT_DIR = Path(__file__).parent.parent
PROMPTS_DIR = SCRIPT_DIR / "prompts"

MODEL = "claude-sonnet-4-5-20250929"  # Balance of cost/quality for bulk extraction
MAX_TOKENS = 4096
RETRY_ATTEMPTS = 3
RETRY_DELAY = 5  # seconds


def load_prompt(prompt_name: str) -> str:
    """Load a prompt template from the prompts directory."""
    prompt_path = PROMPTS_DIR / f"{prompt_name}.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def image_to_base64(image_path: str) -> tuple[str, str]:
    """Read image and return (base64_data, media_type)."""
    path = Path(image_path)
    ext = path.suffix.lower()
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
    media_type = media_types.get(ext, "image/png")
    
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    
    return data, media_type


def extract_card_side(client: anthropic.Anthropic, image_path: str, prompt_name: str) -> dict:
    """
    Send a single card image to Claude with the specified prompt.
    Returns parsed JSON dict or error dict.
    """
    prompt_text = load_prompt(prompt_name)
    img_data, media_type = image_to_base64(image_path)
    
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": img_data,
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt_text,
                        }
                    ]
                }]
            )
            
            # Extract text content
            text = ""
            for block in response.content:
                if block.type == "text":
                    text += block.text
            
            # Parse JSON from response (strip markdown fences if present)
            text = text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            
            parsed = json.loads(text)
            parsed["_extraction_meta"] = {
                "source_image": str(image_path),
                "model_used": MODEL,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "attempt": attempt + 1,
            }
            return parsed
            
        except json.JSONDecodeError as e:
            print(f"  JSON parse error on attempt {attempt + 1}: {e}")
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
            else:
                return {"error": f"JSON parse failed after {RETRY_ATTEMPTS} attempts", 
                        "raw_text": text[:500]}
        
        except anthropic.RateLimitError:
            wait = RETRY_DELAY * (attempt + 1) * 2
            print(f"  Rate limited, waiting {wait}s...")
            time.sleep(wait)
        
        except Exception as e:
            print(f"  API error on attempt {attempt + 1}: {e}")
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
            else:
                return {"error": str(e)}
    
    return {"error": "Max retries exceeded"}


def extract_stat_card(client: anthropic.Anthropic, front_path: str, back_path: str) -> dict:
    """
    Extract a complete stat card from front + back images.
    Returns merged result with both sides' data.
    """
    print(f"  Extracting front: {Path(front_path).name}")
    front = extract_card_side(client, front_path, "front_prompt")
    
    if "error" in front:
        return {"error": f"Front extraction failed: {front['error']}", "front": front}
    
    print(f"  Extracting back: {Path(back_path).name}")
    back = extract_card_side(client, back_path, "back_prompt")
    
    if "error" in back:
        return {"error": f"Back extraction failed: {back['error']}", "front": front, "back": back}
    
    return {"front": front, "back": back, "status": "extracted"}


def extract_crew_card(client: anthropic.Anthropic, image_path: str) -> dict:
    """Extract a crew card from a single image."""
    print(f"  Extracting crew card: {Path(image_path).name}")
    result = extract_card_side(client, image_path, "crew_card_prompt")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract M4E card data via Claude API")
    parser.add_argument("images", nargs="+", help="Image file(s) â€” 2 for stat card (front, back), 1 for crew")
    parser.add_argument("--card-type", choices=["stat", "crew"], default="stat")
    parser.add_argument("--output", "-o", required=True, help="Output JSON file")
    parser.add_argument("--model", default=MODEL, help=f"Claude model (default: {MODEL})")
    args = parser.parse_args()
    
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY environment variable")
        sys.exit(1)
    
    MODEL = args.model
    client = anthropic.Anthropic(api_key=api_key)
    
    if args.card_type == "stat":
        if len(args.images) != 2:
            print("ERROR: Stat cards require exactly 2 images (front, back)")
            sys.exit(1)
        result = extract_stat_card(client, args.images[0], args.images[1])
    else:
        if len(args.images) != 1:
            print("ERROR: Crew cards require exactly 1 image")
            sys.exit(1)
        result = extract_crew_card(client, args.images[0])
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    
    print(f"Output written to {args.output}")
