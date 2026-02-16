"""
fix_casing.py — Find and fix ALL CAPS model names in the database.

Applies Title Case with proper English rules:
- Minor words (of, the, a, an, in, on, at, for, to, and, or) stay lowercase unless first word
- Preserves acronyms like K.O.T.O.
- Handles special names like LaCroix, McTavish, LeBlanc

Usage:
  python fix_casing.py              # Preview
  python fix_casing.py --apply      # Apply fixes
"""
import sqlite3, sys, re

DRY_RUN = "--apply" not in sys.argv
DB_PATH = "db/m4e.db"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Special casing overrides
SPECIAL_NAMES = {
    "LACROIX": "LaCroix",
    "LEBLANC": "LeBlanc",
    "MCTAVISH": "McTavish",
}

# Minor words that stay lowercase (unless first word or first after open paren)
MINOR_WORDS = {"of", "the", "a", "an", "in", "on", "at", "for", "to", "and", "or", "but", "nor"}

def is_all_caps(s):
    letters = [ch for ch in s if ch.isalpha()]
    return len(letters) > 1 and all(ch.isupper() for ch in letters)

def is_acronym(word):
    clean = word.strip("()")
    if re.match(r'^([A-Z]\.){2,}[A-Z]?\.?$', clean):
        return True
    return False

def smart_title_word(word, is_first):
    """Title-case a single word, respecting special rules."""
    # Strip parens for processing
    prefix = ""
    suffix = ""
    if word.startswith("("):
        prefix = "("
        word = word[1:]
    if word.endswith(")"):
        suffix = ")"
        word = word[:-1]

    # Acronym — preserve
    if is_acronym(word.upper()):
        return prefix + word.upper() + suffix

    # Special names
    upper_clean = word.upper().replace("'", "").replace("-", "")
    for pattern, replacement in SPECIAL_NAMES.items():
        if pattern in upper_clean:
            result = word.upper().replace(pattern, replacement)
            return prefix + result + suffix

    # Hyphenated
    if "-" in word:
        parts = word.split("-")
        word = "-".join(p.capitalize() for p in parts)
    else:
        word = word.capitalize()

    # Minor word rule: lowercase unless first word or first after open paren
    is_first_in_group = is_first or prefix == "("
    if word.lower() in MINOR_WORDS and not is_first_in_group:
        word = word.lower()

    return prefix + word + suffix

def smart_title(name):
    words = name.split()
    return " ".join(smart_title_word(w, i == 0) for i, w in enumerate(words))


# Find ALL CAPS names
rows = c.execute("SELECT id, name, title, faction FROM models ORDER BY name").fetchall()

fixes = []
for model_id, name, title, faction in rows:
    new_name = name
    new_title = title

    if is_all_caps(name):
        new_name = smart_title(name)
    
    if title and is_all_caps(title):
        new_title = smart_title(title)
    
    if new_name != name or new_title != title:
        fixes.append((model_id, name, title, new_name, new_title, faction))

print(f"Found {len(fixes)} models with ALL CAPS names:\n")
for model_id, old_name, old_title, new_name, new_title, faction in fixes:
    old = f"{old_name}" + (f" ({old_title})" if old_title else "")
    new = f"{new_name}" + (f" ({new_title})" if new_title else "")
    print(f"  id={model_id:>4}  {old}  ->  {new}")

if DRY_RUN:
    print(f"\nDry run — use --apply to update {len(fixes)} models.")
else:
    for model_id, old_name, old_title, new_name, new_title, faction in fixes:
        c.execute("UPDATE models SET name=?, title=? WHERE id=?",
                  (new_name, new_title, model_id))
    conn.commit()
    print(f"\nDone — {len(fixes)} models updated.")

conn.close()
